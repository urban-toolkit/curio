/**
 * An Autark map opens framed on the layers it draws (#773), not 10,000 world
 * units above its origin whatever they hold.
 */
import { drawnExtent, frameMaps, framingCamera } from "../../../adapters/node/autkMapView";

const FOVY = (45 * Math.PI) / 180;
const FAR = 5e5;

// autk-map's camera as frameMaps uses it.
function fakeCamera() {
  return {
    resetCamera: jest.fn(),
    resize: jest.fn(),
    getFovyRadians: () => FOVY,
    getFar: () => FAR,
  };
}

// An AutkMap with its layers, its camera and a canvas laid out at width by height.
function fakeMap(layers: any[], width = 480, height = 300) {
  const canvas = document.createElement("canvas");
  Object.defineProperty(canvas, "offsetWidth", { get: () => width, configurable: true });
  Object.defineProperty(canvas, "offsetHeight", { get: () => height, configurable: true });
  const ownReset = jest.fn();
  const map: any = {
    canvas,
    camera: fakeCamera(),
    renderer: { pixelWidth: width * 2, pixelHeight: height * 2 },
    layerManager: { layers },
    resetCamera: ownReset,
    requestRender: jest.fn(),
  };
  return { map, ownReset, canvas };
}

// A flat layer's mesh, x, y per vertex, around (cx, cy), w by h.
function flatLayer(cx: number, cy: number, w: number, h: number) {
  return {
    position: new Float32Array([cx - w / 2, cy - h / 2, cx + w / 2, cy - h / 2, cx + w / 2, cy + h / 2, cx - w / 2, cy + h / 2]),
    _dimension: 2,
  };
}

describe("drawnExtent", () => {
  test("joins every layer's vertices: flat meshes, a raster's quad, points and buildings with their heights", () => {
    const buildings = { position: new Float32Array([-300, -200, 0, 300, 200, 234, 0, 0, 120]), _dimension: 3 };
    const raster = { position: new Float32Array([-400, -100, 400, -100, 400, 100, -400, 100]) };
    const points = { pointInstances: new Float32Array([10, 500, -20, -450]) };
    expect(drawnExtent([buildings, raster, points])).toEqual({ minX: -400, minY: -450, maxX: 400, maxY: 500, top: 234 });
  });

  test("a layer that drew nothing adds nothing, and no geometry is no extent", () => {
    expect(drawnExtent([{ position: new Float32Array(0), _dimension: 2 }, { layerInfo: {} }])).toBeNull();
    expect(drawnExtent([])).toBeNull();
  });
});

describe("framingCamera", () => {
  test("autk-map's terrain fit: straight down on the middle, the extent's limiting side over the view with 8% to spare", () => {
    const { lookAt, eye } = framingCamera({ minX: 100, minY: -50, maxX: 1300, maxY: 650, top: 0 }, 1.6, FOVY);
    expect(lookAt).toEqual([700, 300, 0]);
    expect(eye[0]).toBe(700);
    expect(eye[1]).toBe(300);
    // 1,200 wide on a view 1.6 times wider than tall needs more height than
    // 700 tall: the width is the side that fits.
    const visibleWidth = 2 * Math.tan(FOVY / 2) * 1.6 * eye[2];
    expect(visibleWidth).toBeCloseTo(1200 * 1.08, 6);
  });

  test("a tall extent fits by its height", () => {
    const { eye } = framingCamera({ minX: 0, minY: 0, maxX: 100, maxY: 2000, top: 0 }, 1.6, FOVY);
    expect(2 * Math.tan(FOVY / 2) * eye[2]).toBeCloseTo(2000 * 1.08, 6);
  });

  test("buildings lift the camera by the tallest, so the roofs fit as the ground would", () => {
    const flat = framingCamera({ minX: 0, minY: 0, maxX: 1200, maxY: 700, top: 0 }, 1.6, FOVY);
    const tall = framingCamera({ minX: 0, minY: 0, maxX: 1200, maxY: 700, top: 234 }, 1.6, FOVY);
    expect(tall.eye[2] - flat.eye[2]).toBeCloseTo(234, 6);
  });

  test("never past half of the far plane, where a country-sized extent would be clipped away", () => {
    const { eye } = framingCamera({ minX: 0, minY: 0, maxX: 4.5e6, maxY: 3e6, top: 0 }, 1.6, FOVY, FAR);
    expect(eye[2]).toBe(FAR / 2);
  });
});

describe("frameMaps", () => {
  test("each map's camera frames the layers it drew, once per map however many dataRefs it draws", () => {
    // The Loop's few blocks, about 1,200 by 700 around (40, -10) from the origin.
    const { map } = fakeMap([flatLayer(40, -10, 1200, 700), flatLayer(40, -10, 600, 300)]);
    frameMaps({ _mapRegistry: new Map([["input_0", map], ["input_1", map]]) });

    expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
    const [up, lookAt, eye] = map.camera.resetCamera.mock.calls[0];
    expect(up).toEqual([0, 1, 0]);
    expect(lookAt).toEqual([40, -10, 0]);
    expect(eye).toEqual(framingCamera({ minX: -560, minY: -360, maxX: 640, maxY: 340, top: 0 }, 1.6, FOVY, FAR).eye);
    // autk-map's own default is 10,000 units up: this is about 7 times closer.
    expect(eye[2]).toBeLessThan(10000 / 6);
    expect(map.camera.resize).toHaveBeenCalledWith(960, 600);
  });

  test("the map's R key frames it the same way", () => {
    const { map, ownReset } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    frameMaps({ _mapRegistry: new Map([["input_0", map]]) });
    map.camera.resetCamera.mockClear();
    map.resetCamera();
    expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(ownReset).not.toHaveBeenCalled();
  });

  test("a map that drew one point, or nothing, keeps autk-map's own view", () => {
    const one = fakeMap([{ pointInstances: new Float32Array([5, 5]) }]);
    const none = fakeMap([]);
    frameMaps({ _mapRegistry: new Map([["input_0", one.map], ["input_1", none.map]]) });
    expect(one.map.camera.resetCamera).not.toHaveBeenCalled();
    expect(none.map.camera.resetCamera).not.toHaveBeenCalled();
    expect(one.ownReset).toHaveBeenCalledTimes(1);
    expect(none.ownReset).toHaveBeenCalledTimes(1);
  });

  test("a map in terrain mode is left to autk-map, which fits it itself", () => {
    const { map, ownReset } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    map._terrainRenderPath = {};
    frameMaps({ _mapRegistry: new Map([["input_0", map]]) });
    expect(map.camera.resetCamera).not.toHaveBeenCalled();
    expect(map.resetCamera).toBe(ownReset);
  });

  test("a map drawn while hidden is framed when it is first shown, at the size it is shown at", () => {
    let shown = { width: 0, height: 0 };
    const { map, canvas } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    Object.defineProperty(canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(canvas, "offsetHeight", { get: () => shown.height });
    frameMaps({ _mapRegistry: new Map([["input_0", map]]) });
    expect(map.camera.resetCamera).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("resize"));
    expect(map.camera.resetCamera).not.toHaveBeenCalled();

    shown = { width: 300, height: 600 };
    window.dispatchEvent(new Event("resize"));
    expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
    const eye = map.camera.resetCamera.mock.calls[0][2];
    expect(eye).toEqual(framingCamera({ minX: -600, minY: -350, maxX: 600, maxY: 350, top: 0 }, 0.5, FOVY, FAR).eye);

    // Once only: a later resize keeps whatever view the map has by then.
    window.dispatchEvent(new Event("resize"));
    expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
  });

  test("a map framed is asked for a frame, since it draws on demand: at once, on the R key and when first shown", () => {
    const { map } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    frameMaps({ _mapRegistry: new Map([["input_0", map]]) });
    expect(map.requestRender).toHaveBeenCalledTimes(1);
    map.resetCamera();
    expect(map.requestRender).toHaveBeenCalledTimes(2);

    let shown = { width: 0, height: 0 };
    const hidden = fakeMap([flatLayer(0, 0, 1200, 700)]);
    Object.defineProperty(hidden.canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(hidden.canvas, "offsetHeight", { get: () => shown.height });
    frameMaps({ _mapRegistry: new Map([["input_0", hidden.map]]) });
    expect(hidden.map.requestRender).not.toHaveBeenCalled();
    shown = { width: 300, height: 600 };
    window.dispatchEvent(new Event("resize"));
    expect(hidden.map.requestRender).toHaveBeenCalledTimes(1);
  });

  test("a grammar with no maps, or a map without autk-map's camera, is left alone", () => {
    expect(() => frameMaps({})).not.toThrow();
    expect(() => frameMaps({ _mapRegistry: new Map([["input_0", {}]]) })).not.toThrow();
  });
});
