/**
 * An Autark map opens framed on the layers it draws (#773), not 10,000 world
 * units above its origin whatever they hold.
 */
import { drawnExtent, frameMaps, framingCamera, keepMapViews, mapViews } from "../../../adapters/node/autkMapView";
import { grammarThatRan } from "../../_support/autkGrammarMaps";

const FOVY = (45 * Math.PI) / 180;
const FAR = 5e5;

// A document of one map with one layer.
const ONE_MAP = { map: { layerRefs: [{ dataRef: "input_0" }] } };

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
    frameMaps(grammarThatRan({ map: { layerRefs: [{ dataRef: "input_0" }, { dataRef: "input_1" }] } }, map));

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
    frameMaps(grammarThatRan(ONE_MAP, map));
    map.camera.resetCamera.mockClear();
    map.resetCamera();
    expect(map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(ownReset).not.toHaveBeenCalled();
  });

  test("a map that drew one point, or nothing, keeps autk-map's own view", () => {
    const one = fakeMap([{ pointInstances: new Float32Array([5, 5]) }]);
    const none = fakeMap([]);
    frameMaps(grammarThatRan({
      map: [{ layerRefs: [{ dataRef: "input_0" }] }, { layerRefs: [{ dataRef: "input_1" }] }],
    }, one.map, none.map));
    expect(one.map.camera.resetCamera).not.toHaveBeenCalled();
    expect(none.map.camera.resetCamera).not.toHaveBeenCalled();
    expect(one.ownReset).toHaveBeenCalledTimes(1);
    expect(none.ownReset).toHaveBeenCalledTimes(1);
  });

  test("a map in terrain mode is left to autk-map, which fits it itself", () => {
    const { map, ownReset } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    map._terrainRenderPath = {};
    frameMaps(grammarThatRan(ONE_MAP, map));
    expect(map.camera.resetCamera).not.toHaveBeenCalled();
    expect(map.resetCamera).toBe(ownReset);
  });

  test("a map drawn while hidden is framed when it is first shown, at the size it is shown at", () => {
    let shown = { width: 0, height: 0 };
    const { map, canvas } = fakeMap([flatLayer(0, 0, 1200, 700)]);
    Object.defineProperty(canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(canvas, "offsetHeight", { get: () => shown.height });
    frameMaps(grammarThatRan(ONE_MAP, map));
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
    frameMaps(grammarThatRan(ONE_MAP, map));
    expect(map.requestRender).toHaveBeenCalledTimes(1);
    map.resetCamera();
    expect(map.requestRender).toHaveBeenCalledTimes(2);

    let shown = { width: 0, height: 0 };
    const hidden = fakeMap([flatLayer(0, 0, 1200, 700)]);
    Object.defineProperty(hidden.canvas, "offsetWidth", { get: () => shown.width });
    Object.defineProperty(hidden.canvas, "offsetHeight", { get: () => shown.height });
    frameMaps(grammarThatRan(ONE_MAP, hidden.map));
    expect(hidden.map.requestRender).not.toHaveBeenCalled();
    shown = { width: 300, height: 600 };
    window.dispatchEvent(new Event("resize"));
    expect(hidden.map.requestRender).toHaveBeenCalledTimes(1);
  });

  test("a grammar with no maps, or a map without autk-map's camera, is left alone", () => {
    expect(() => frameMaps({})).not.toThrow();
    expect(() => frameMaps(grammarThatRan(ONE_MAP, {}))).not.toThrow();
  });

  test("each of two maps that draw one table is framed on what it drew", () => {
    const first = fakeMap([flatLayer(40, -10, 1200, 700)]);
    const second = fakeMap([flatLayer(40, -10, 1200, 700)]);
    frameMaps(grammarThatRan({
      map: [{ layerRefs: [{ dataRef: "input_0" }] }, { layerRefs: [{ dataRef: "input_0" }] }],
    }, first.map, second.map));
    expect(first.map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(second.map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(first.map.camera.resetCamera.mock.calls[0][1]).toEqual([40, -10, 0]);
  });
});

// A map drawn again after an edit (the Map Edits node's) keeps its view.
describe("mapViews and keepMapViews", () => {
  /** A map whose camera stands at *view*, its layers drawn relative to *origin*. */
  function viewedMap(view: { eye: number[]; lookAt: number[]; up: number[] }, origin: number[] | null) {
    const made = fakeMap([flatLayer(0, 0, 1200, 700)]);
    Object.assign(made.map.camera, {
      getEye: () => [...view.eye],
      getLookAt: () => [...view.lookAt],
      getUp: () => [...view.up],
    });
    made.map.layerManager = {
      layers: made.map.layerManager.layers,
      hasOrigin: origin !== null,
      get origin() {
        if (origin === null) throw new Error("Layer origin has not been initialized");
        return origin;
      },
    };
    return made;
  }
  const ZOOMED = { eye: [120, -40, 300], lookAt: [120, -40, 0], up: [0, 1, 0] };

  test("a map's view is its camera's eye, look-at and up, with the origin its layers are drawn from", () => {
    const { map } = viewedMap(ZOOMED, [1000, 2000]);
    const terrain = viewedMap(ZOOMED, [0, 0]);
    terrain.map._terrainRenderPath = {};
    const unready = viewedMap(ZOOMED, null);
    expect(mapViews(grammarThatRan({
      map: [
        { layerRefs: [{ dataRef: "input_0" }] },
        { layerRefs: [{ dataRef: "input_0" }] },
        { layerRefs: [{ dataRef: "input_0" }] },
      ],
    }, map, terrain.map, unready.map))).toEqual([
      { ...ZOOMED, origin: [1000, 2000] },
      null,
      { ...ZOOMED, origin: null },
    ]);
    expect(mapViews({})).toEqual([]);
  });

  test("a redraw puts the camera back where the last map's was, not framed on the layers", () => {
    const before = viewedMap(ZOOMED, [1000, 2000]);
    const views = mapViews(grammarThatRan(ONE_MAP, before.map));
    const after = viewedMap({ eye: [0, 0, 10000], lookAt: [0, 0, 0], up: [0, 1, 0] }, [1000, 2000]);

    keepMapViews(grammarThatRan(ONE_MAP, after.map), views);

    expect(after.map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(after.map.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], [120, -40, 0], [120, -40, 300]);
    expect(after.map.camera.resize).toHaveBeenCalledWith(960, 600);
    expect(after.map.requestRender).toHaveBeenCalledTimes(1);
  });

  test("when a removal moves the map's origin, the camera moves with it and the same ground stays in view", () => {
    const before = viewedMap(ZOOMED, [1000, 2000]);
    const views = mapViews(grammarThatRan(ONE_MAP, before.map));
    // A building at the first layer's edge is gone: its middle moved 10 east and 5 south.
    const after = viewedMap(ZOOMED, [1010, 1995]);

    keepMapViews(grammarThatRan(ONE_MAP, after.map), views);

    // The ground at (1120, 1960) is at (110, -35) from the new origin.
    expect(after.map.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], [110, -35, 0], [110, -35, 300]);
  });

  test("a map with no view to keep is framed on its layers, and the R key frames a kept map", () => {
    const first = viewedMap(ZOOMED, [0, 0]);
    const second = viewedMap(ZOOMED, [0, 0]);
    keepMapViews(grammarThatRan({
      map: [{ layerRefs: [{ dataRef: "input_0" }] }, { layerRefs: [{ dataRef: "input_0" }] }],
    }, first.map, second.map), [{ ...ZOOMED, origin: [0, 0] }]);
    expect(first.map.camera.resetCamera.mock.calls[0][1]).toEqual([120, -40, 0]);
    expect(second.map.camera.resetCamera.mock.calls[0][1]).toEqual([0, 0, 0]);

    first.map.camera.resetCamera.mockClear();
    first.map.resetCamera();
    expect(first.map.camera.resetCamera).toHaveBeenCalledTimes(1);
    expect(first.map.camera.resetCamera.mock.calls[0][1]).toEqual([0, 0, 0]);
    expect(first.ownReset).not.toHaveBeenCalled();
  });
});
