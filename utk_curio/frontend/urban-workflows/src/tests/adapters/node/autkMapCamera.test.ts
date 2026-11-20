/**
 * A map's `camera` turns the view an Autark node frames the map at
 * (adapters/node/autkMapView). Each map is framed on the layers it drew, then
 * turned by the `camera` of its own `map` entry through autk-grammar's own
 * `applyCamera`: the eye goes round the point the map looks at, as far from it
 * as the framing put it (or as `zoom` says), `pitch` degrees from straight
 * down, facing `bearing` degrees clockwise from north, which is then up the
 * screen. The R key frames and turns the map again. A draw that keeps the view
 * (a Map Editor's edit) puts back the view the map had, moved or not, and never
 * turns it a second time, unless the entry's camera changed.
 *
 * `applyCamera` is the grammar's build (_support/autkApplyCamera). Each view
 * expected here is worked out from the framing and the angles.
 */
jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => ({}), { virtual: true });
// The one export the grammar's build reads of autk-core as it loads.
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkApplyCamera").autkCoreAtLoad(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => ({}), { virtual: true });

import {
  attachSpecCameras, frameMaps, framingCamera, keepMapViews, mapViews, showFramedViews,
} from "../../../adapters/node/autkMapView";
import { grammarThatRan } from "../../_support/autkGrammarMaps";
import { grammarApplyCamera, grammarResolveCameraCenter } from "../../_support/autkApplyCamera";

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

/**
 * An AutkMap with *layers*, its canvas laid out at 480 by 300, its layers drawn
 * from *origin*. autk-map's own reset (`ownReset`, its R key) puts the camera
 * 10,000 units straight above the origin.
 */
function cameraMap(layers: any[], origin: number[] = [1000, 2000]) {
  const canvas = document.createElement("canvas");
  Object.defineProperty(canvas, "offsetWidth", { get: () => WIDTH, configurable: true });
  Object.defineProperty(canvas, "offsetHeight", { get: () => HEIGHT, configurable: true });
  const camera = standingCamera();
  const map: any = {
    canvas,
    camera,
    renderer: { pixelWidth: WIDTH * 2, pixelHeight: HEIGHT * 2 },
    layerManager: { layers, hasOrigin: true, origin },
    requestRender: jest.fn(),
  };
  const ownReset = jest.fn(() => {
    camera.resetCamera([0, 1, 0], [0, 0, 0], [0, 0, 10000]);
    camera.resize(map.renderer.pixelWidth, map.renderer.pixelHeight);
  });
  map.resetCamera = ownReset;
  return { map, ownReset, canvas };
}

/** A flat layer's mesh, x, y per vertex, around (cx, cy), w by h. */
function flatLayer(cx: number, cy: number, w: number, h: number) {
  return {
    position: new Float32Array([cx - w / 2, cy - h / 2, cx + w / 2, cy - h / 2, cx + w / 2, cy + h / 2, cx - w / 2, cy + h / 2]),
    _dimension: 2,
  };
}

/** The Loop's few blocks: about 1,200 by 700 around (40, -10) from the origin. */
const BLOCKS = () => [flatLayer(40, -10, 1200, 700)];

/** Where Curio frames BLOCKS: straight down on (40, -10), as high as fits them. */
const FRAMED = framingCamera({ minX: -560, minY: -360, maxX: 640, maxY: 340, top: 0 }, WIDTH / HEIGHT, FOVY, FAR);
const HIGH = FRAMED.eye[2];

/**
 * The view turned round *lookAt* on the ground: the eye *distance* away from
 * it, *pitch* degrees from straight down, facing *bearing* degrees clockwise
 * from north, with that heading up the screen: its up direction across its
 * line of sight, toward the far side of the view, as autk-map's own tilt
 * leaves it.
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

/** A map entry drawing `input_0`, with *camera* when one is given. */
const mapEntry = (camera?: Record<string, unknown>) => ({
  ...(camera ? { camera } : {}),
  layerRefs: [{ dataRef: "input_0" }],
});
const oneMap = (camera?: Record<string, unknown>) => ({ map: mapEntry(camera) });

/** The grammar that ran *spec* and drew *maps*, each map given its entry's camera, as the node gives it. */
function drawn(spec: any, ...maps: any[]) {
  const grammar = grammarThatRan(spec, ...maps);
  attachSpecCameras(grammar, spec, applyCamera);
  return grammar;
}

describe("a map's camera", () => {
  test("turns the framed view: round the middle of the layers, as far as the framing put the eye, pitch from straight down, facing bearing", () => {
    const { map } = cameraMap(BLOCKS());
    frameMaps(drawn(oneMap({ pitch: 50, bearing: 30 }), map));

    // Framed first, straight down on the middle of the layers, then turned there.
    const calls = map.camera.resetCamera.mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual([[0, 1, 0], FRAMED.lookAt, FRAMED.eye]);
    expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
    // The matrices are built for the turned view, and the map draws it.
    const lastReset = Math.max(...map.camera.resetCamera.mock.invocationCallOrder);
    const lastResize = Math.max(...map.camera.resize.mock.invocationCallOrder);
    expect(lastResize).toBeGreaterThan(lastReset);
    expect(map.camera.resize).toHaveBeenLastCalledWith(960, 600);
    expect(map.requestRender).toHaveBeenCalled();
  });

  test("with a zoom, the eye is 10000 / 2^(zoom - 10) units from the middle: 625 at zoom 14, 312.5 at zoom 15", () => {
    const above = cameraMap(BLOCKS());
    frameMaps(drawn(oneMap({ zoom: 14 }), above.map));
    expectView(above.map.camera.view, turned(FRAMED.lookAt, 625, 0, 0));

    const tilted = cameraMap(BLOCKS());
    frameMaps(drawn(oneMap({ zoom: 15, pitch: 40, bearing: 300 }), tilted.map));
    expectView(tilted.map.camera.view, turned(FRAMED.lookAt, 312.5, 40, 300));
  });

  test("no camera, or one that asks for nothing, leaves the framed view straight down", () => {
    for (const camera of [undefined, {}, { pitch: 0, bearing: 0 }]) {
      const { map } = cameraMap(BLOCKS());
      frameMaps(drawn(oneMap(camera), map));
      expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
      expectView(map.camera.view, { eye: FRAMED.eye, lookAt: FRAMED.lookAt, up: [0, 1, 0] });
    }
  });

  test("the R key frames the map and turns it again, from wherever it was moved, and a second press changes nothing", () => {
    const { map, ownReset } = cameraMap(BLOCKS());
    frameMaps(drawn(oneMap({ pitch: 50, bearing: 30 }), map));
    const opened = map.camera.view;

    // The person pans and zooms.
    map.camera.resetCamera([0, 1, 0], [300, 200, 0], [300, 200, 90]);
    map.resetCamera();
    expectView(map.camera.view, opened);
    const once = map.camera.view;
    map.resetCamera();
    expect(map.camera.view).toEqual(once);
    expect(ownReset).not.toHaveBeenCalled();
  });

  test("each map of a document turns by the camera of its own entry", () => {
    const north = cameraMap(BLOCKS());
    const plain = cameraMap(BLOCKS());
    const east = cameraMap(BLOCKS());
    frameMaps(drawn(
      { map: [mapEntry({ pitch: 30 }), mapEntry(), mapEntry({ bearing: 90 })] },
      north.map, plain.map, east.map,
    ));
    expectView(north.map.camera.view, turned(FRAMED.lookAt, HIGH, 30, 0));
    expectView(plain.map.camera.view, turned(FRAMED.lookAt, HIGH, 0, 0));
    expectView(east.map.camera.view, turned(FRAMED.lookAt, HIGH, 0, 90));
  });

  test("a map drawn while hidden is framed and turned when it is first shown", () => {
    let shown = { width: 0, height: 0 };
    const { map, canvas } = cameraMap(BLOCKS());
    Object.defineProperty(canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(canvas, "offsetHeight", { get: () => shown.height });
    frameMaps(drawn(oneMap({ pitch: 45, bearing: 180 }), map));
    expect(map.camera.resetCamera).not.toHaveBeenCalled();

    shown = { width: WIDTH, height: HEIGHT };
    window.dispatchEvent(new Event("resize"));
    expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 45, 180));
  });

  test("a map with nothing to frame keeps autk-map's own view, turned by its camera as the grammar turns it", () => {
    const { map, ownReset } = cameraMap([{ pointInstances: new Float32Array([5, 5]) }]);
    frameMaps(drawn(oneMap({ pitch: 60, bearing: 45 }), map));
    expect(ownReset).toHaveBeenCalledTimes(1);
    // autk-map's own view looks at the origin from 10,000 units up.
    expectView(map.camera.view, turned([0, 0, 0], 10000, 60, 45));
    expect(map.requestRender).toHaveBeenCalled();
  });

  test("a map in terrain mode keeps the view its terrain fits; its R key fits the terrain again and turns it by its camera", () => {
    const { map, ownReset } = cameraMap(BLOCKS());
    map._terrainRenderPath = {};
    frameMaps(drawn(oneMap({ pitch: 50, bearing: 30 }), map));
    // The grammar's run fitted the camera to the terrain and turned it: Curio
    // does not frame the map on its layers.
    expect(map.camera.resetCamera).not.toHaveBeenCalled();
    // The R key: autk-map's own fit, the terrain's, then the turn.
    map.resetCamera();
    expect(ownReset).toHaveBeenCalledTimes(1);
    expectView(map.camera.view, turned([0, 0, 0], 10000, 50, 30));
  });
});

/** A tour's steps, as a document writes them. */
const TOUR = [{ type: "zoom", amount: 1, seconds: 2 }, { type: "bearing", amount: 90, seconds: 3 }];

/** Every argument autk-grammar 5.4.0's player takes: `attachSpecCameras` with the player as its fourth. */
const attachWithTours = attachSpecCameras as (...args: any[]) => void;

/**
 * autk-grammar's `playCameraMotion`, standing in: each tour it plays, the map
 * and the steps, and the view the tour starts from.
 */
function tourPlayer() {
  const played: Array<{ map: any; motion: any[]; from: View }> = [];
  const play = jest.fn((map: any, motion: any[]) => {
    played.push({ map, motion, from: { ...map.camera.view } });
    return { done: Promise.resolve(), stop: jest.fn() };
  });
  return { play, played };
}

/** The grammar that ran *spec* and drew *maps*, each map given its entry's camera and the tour player *play*. */
function drawnWithTours(spec: any, play: unknown, ...maps: any[]) {
  const grammar = grammarThatRan(spec, ...maps);
  attachWithTours(grammar, spec, applyCamera, play);
  return grammar;
}

describe("a camera tour", () => {
  const MOVED: View = { eye: [250, 120, 160], lookAt: [300, 200, 0], up: [0, 1, 0] };

  test("plays once the map is framed and turned, from the turned view", () => {
    const { play, played } = tourPlayer();
    const { map } = cameraMap(BLOCKS());
    frameMaps(drawnWithTours(oneMap({ pitch: 50, bearing: 30, motion: TOUR }), play, map));
    expect(play).toHaveBeenCalledTimes(1);
    expect(played[0].map).toBe(map);
    expect(played[0].motion).toEqual(TOUR);
    expectView(played[0].from, turned(FRAMED.lookAt, HIGH, 50, 30));
    // After the camera's last turn: the run's tour, started before the
    // framing, would set the camera at every frame.
    expect(play.mock.invocationCallOrder[0]).toBeGreaterThan(Math.max(...map.camera.resetCamera.mock.invocationCallOrder));
  });

  test("plays again from the framed and turned view when the R key frames the map", () => {
    const { play, played } = tourPlayer();
    const { map } = cameraMap(BLOCKS());
    frameMaps(drawnWithTours(oneMap({ pitch: 50, bearing: 30, motion: TOUR }), play, map));
    map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    map.resetCamera();
    expect(play).toHaveBeenCalledTimes(2);
    expectView(played[1].from, turned(FRAMED.lookAt, HIGH, 50, 30));
  });

  test("a map drawn while hidden plays its tour when it is first shown", () => {
    let shown = { width: 0, height: 0 };
    const { play } = tourPlayer();
    const { map, canvas } = cameraMap(BLOCKS());
    Object.defineProperty(canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(canvas, "offsetHeight", { get: () => shown.height });
    frameMaps(drawnWithTours(oneMap({ motion: TOUR }), play, map));
    expect(play).not.toHaveBeenCalled();

    shown = { width: WIDTH, height: HEIGHT };
    window.dispatchEvent(new Event("resize"));
    expect(play).toHaveBeenCalledTimes(1);
  });

  test("a camera without a motion plays no tour", () => {
    const { play } = tourPlayer();
    const { map } = cameraMap(BLOCKS());
    frameMaps(drawnWithTours(oneMap({ pitch: 50 }), play, map));
    map.resetCamera();
    expect(play).not.toHaveBeenCalled();
  });

  test("a map in terrain mode plays its tour again when its R key fits the terrain and turns it", () => {
    const { play, played } = tourPlayer();
    const { map } = cameraMap(BLOCKS());
    map._terrainRenderPath = {};
    frameMaps(drawnWithTours(oneMap({ pitch: 40, motion: TOUR }), play, map));
    // The run's own tour plays from the terrain's view, which Curio leaves.
    expect(play).not.toHaveBeenCalled();
    map.resetCamera();
    expect(play).toHaveBeenCalledTimes(1);
    expectView(played[0].from, turned([0, 0, 0], 10000, 40, 0));
  });

  test("a draw that puts the view back stops the run's tour and plays none", () => {
    const { play } = tourPlayer();
    const spec = oneMap({ pitch: 50, motion: TOUR });
    const before = cameraMap(BLOCKS());
    const first = drawnWithTours(spec, play, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);
    play.mockClear();

    const after = cameraMap(BLOCKS());
    const second = drawnWithTours(spec, play, after.map);
    // The tour the run started on its new map, from its own view.
    const runTour = { done: Promise.resolve(), stop: jest.fn() };
    (second as any).tours = [runTour];
    keepMapViews(second, views);
    expect(after.map.camera.view).toEqual(MOVED);
    expect(runTour.stop).toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  test("a tour the document changed is another camera: the redraw frames and turns the map, and plays the new tour", () => {
    const { play, played } = tourPlayer();
    const before = cameraMap(BLOCKS());
    const first = drawnWithTours(oneMap({ pitch: 50, motion: TOUR }), play, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    const other = [{ type: "pitch", amount: 10, seconds: 1, pan: 50 }];
    const after = cameraMap(BLOCKS());
    keepMapViews(drawnWithTours(oneMap({ pitch: 50, motion: other }), play, after.map), views);
    expectView(after.map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 0));
    expect(played[played.length - 1].map).toBe(after.map);
    expect(played[played.length - 1].motion).toEqual(other);
  });

  test("the same tour written with its fields in another order is the same camera: the view is put back", () => {
    const { play } = tourPlayer();
    const before = cameraMap(BLOCKS());
    const first = drawnWithTours(oneMap({ pitch: 50, motion: TOUR }), play, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    const reordered = TOUR.map(({ type, amount, seconds }) => ({ seconds, amount, type }));
    const after = cameraMap(BLOCKS());
    keepMapViews(drawnWithTours(oneMap({ motion: reordered, pitch: 50 }), play, after.map), views);
    expect(after.map.camera.view).toEqual(MOVED);
  });

  test("the framing check shows a map's framed view and plays no tour", () => {
    const { play } = tourPlayer();
    const { map } = cameraMap(BLOCKS());
    const grammar = drawnWithTours(oneMap({ pitch: 50, motion: TOUR }), play, map);
    frameMaps(grammar);
    play.mockClear();
    const turnBack = showFramedViews(grammar);
    expectView(map.camera.view, { eye: FRAMED.eye, lookAt: FRAMED.lookAt, up: [0, 1, 0] });
    turnBack();
    expect(play).not.toHaveBeenCalled();
  });
});

describe("a camera's center", () => {
  const MOVED: View = { eye: [250, 120, 160], lookAt: [300, 200, 0], up: [0, 1, 0] };
  /** autk-db, standing in: its transform puts any center at (*x*, *y*) of World Mercator. */
  const transformingTo = (x: number, y: number) => ({
    getWorkspaceConfiguration: () => ({ coordinateFormat: "EPSG:3395" }),
    rawQuery: async () => [{ x, y }],
  });
  const centered = (center: number[]) => oneMap({ center, pitch: 30 });

  test("is where the framed map looks, and a redraw whose center moved frames and turns the map round the new one", async () => {
    const resolveCameraCenter = grammarResolveCameraCenter();
    const before = cameraMap(BLOCKS());
    // The map's origin is (1000, 2000): the center is (300, 250) in its world.
    await resolveCameraCenter(transformingTo(1300, 2250), before.map, [-87.62, 41.88]);
    const first = drawn(centered([-87.62, 41.88]), before.map);
    frameMaps(first);
    expectView(before.map.camera.view, turned([300, 250, 0], HIGH, 30, 0));
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    // The same center: the view the person moved to is put back.
    const same = cameraMap(BLOCKS());
    await resolveCameraCenter(transformingTo(1300, 2250), same.map, [-87.62, 41.88]);
    keepMapViews(drawn(centered([-87.62, 41.88]), same.map), views);
    expect(same.map.camera.view).toEqual(MOVED);

    // Another center is another camera: framed and turned round it.
    const moved = cameraMap(BLOCKS());
    await resolveCameraCenter(transformingTo(900, 1800), moved.map, [-87.63, 41.87]);
    keepMapViews(drawn(centered([-87.63, 41.87]), moved.map), views);
    expectView(moved.map.camera.view, turned([-100, -200, 0], HIGH, 30, 0));
  });
});

// A map drawn again after an edit (one a Map Editor node feeds) keeps its view.
describe("a draw that keeps the view", () => {
  const TILTED = oneMap({ pitch: 50, bearing: 30 });
  const MOVED: View = { eye: [250, 120, 160], lookAt: [300, 200, 0], up: [0, 1, 0] };

  test("puts back the view the person moved the map to, and does not turn it again", () => {
    const before = cameraMap(BLOCKS());
    const first = drawn(TILTED, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    // The same camera, written in another order.
    const after = cameraMap(BLOCKS());
    keepMapViews(drawn(oneMap({ bearing: 30, pitch: 50 }), after.map), views);
    expect(after.map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(after.map.camera.view).toEqual(MOVED);
  });

  test("keeps the camera of a map nobody moved, draw after draw, the eye never closer", () => {
    const opened = cameraMap(BLOCKS());
    let grammar = drawn(TILTED, opened.map);
    frameMaps(grammar);
    const view = opened.map.camera.view;
    expectView(view, turned(FRAMED.lookAt, HIGH, 50, 30));
    for (let draw = 0; draw < 3; draw += 1) {
      const next = cameraMap(BLOCKS());
      const views = mapViews(grammar);
      grammar = drawn(TILTED, next.map);
      keepMapViews(grammar, views);
      expectView(next.map.camera.view, view);
    }
  });

  test("frames a map whose camera the document changed, and turns it by the new camera", () => {
    const before = cameraMap(BLOCKS());
    const first = drawn(TILTED, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    const after = cameraMap(BLOCKS());
    keepMapViews(drawn(oneMap({ pitch: 20, bearing: 270 }), after.map), views);
    expectView(after.map.camera.view, turned(FRAMED.lookAt, HIGH, 20, 270));
  });

  test("frames a map whose camera the document took out straight down on its layers", () => {
    const before = cameraMap(BLOCKS());
    const first = drawn(TILTED, before.map);
    frameMaps(first);
    const views = mapViews(first);

    const after = cameraMap(BLOCKS());
    keepMapViews(drawn(oneMap(), after.map), views);
    expectView(after.map.camera.view, turned(FRAMED.lookAt, HIGH, 0, 0));
  });

  test("keeps the view of a map in terrain mode, as it keeps a flat map's", () => {
    const before = cameraMap(BLOCKS());
    before.map._terrainRenderPath = {};
    const first = drawn(TILTED, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    const after = cameraMap(BLOCKS());
    after.map._terrainRenderPath = {};
    keepMapViews(drawn(TILTED, after.map), views);
    expect(after.map.camera.view).toEqual(MOVED);
  });

  test("the R key on a map put back frames and turns it by its camera", () => {
    const before = cameraMap(BLOCKS());
    const first = drawn(TILTED, before.map);
    frameMaps(first);
    before.map.camera.resetCamera(MOVED.up, MOVED.lookAt, MOVED.eye);
    const views = mapViews(first);

    const after = cameraMap(BLOCKS());
    keepMapViews(drawn(TILTED, after.map), views);
    expect(after.map.camera.view).toEqual(MOVED);
    after.map.resetCamera();
    expectView(after.map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
    expect(after.ownReset).not.toHaveBeenCalled();
  });
});
