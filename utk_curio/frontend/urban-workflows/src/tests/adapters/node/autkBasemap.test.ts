/**
 * The basemap toggle under an Autark map: OpenStreetMap's land, parks, water
 * and roads for the map's extent, loaded once and then shown or hidden.
 */
jest.mock("../../../services/api", () => ({ fetchRaster: jest.fn() }));

import {
  BASEMAP_LAYERS,
  basemapLayerId,
  clearBasemapCache,
  mapExtent,
  setBasemap,
  worldMercatorToLonLat,
} from "../../../adapters/node/autkBasemap";

// EPSG:3395 forward, to check the inverse against.
const A = 6378137;
const E = 0.0818191908426215;
function lonLatToWorldMercator(lon: number, lat: number): [number, number] {
  const phi = (lat * Math.PI) / 180;
  const s = E * Math.sin(phi);
  const y = A * Math.log(Math.tan(Math.PI / 4 + phi / 2) * Math.pow((1 - s) / (1 + s), E / 2));
  return [(A * lon * Math.PI) / 180, y];
}

// A map as setBasemap uses it: its origin, its layers, loadCollection and updateRenderInfo.
function fakeMap(origin: [number, number], layers: any[]) {
  const map: any = {
    layerManager: {
      hasOrigin: true,
      origin,
      layers,
      searchByLayerId: (id: string) => layers.find((l) => l.layerInfo.id === id) ?? null,
    },
    loadCollection: jest.fn((id: string, { type }: any) => {
      layers.push({ layerInfo: { id, typeLayer: type }, position: new Float32Array() });
    }),
    updateRenderInfo: jest.fn(),
  };
  return map;
}

function fakeDb() {
  return {
    loadOsm: jest.fn().mockResolvedValue({}),
    getLayer: jest.fn(async (name: string) =>
      name.endsWith("_water") ? { features: [] } : { type: "FeatureCollection", features: [{ name }] }),
  };
}

beforeEach(() => clearBasemapCache());

describe("worldMercatorToLonLat", () => {
  test.each([[-87.63, 41.88], [0, 0], [151.2, -33.87], [10, 70]])("inverts EPSG:3395 at %p, %p", (lon, lat) => {
    const [x, y] = lonLatToWorldMercator(lon, lat);
    const [lon2, lat2] = worldMercatorToLonLat(x, y);
    expect(lon2).toBeCloseTo(lon, 9);
    expect(lat2).toBeCloseTo(lat, 9);
  });
});

describe("mapExtent", () => {
  test("is the map's own layers' extent in degrees, with a margin, and leaves the basemap out", () => {
    const origin = lonLatToWorldMercator(-87.63, 41.88);
    const map = fakeMap(origin, [
      // Buildings carry three values a vertex.
      { layerInfo: { id: "input_0", typeLayer: "buildings" }, position: new Float32Array([-1000, -500, 30, 1000, 500, 10]) },
      { layerInfo: { id: basemapLayerId("roads"), typeLayer: "roads" }, position: new Float32Array([-90000, -90000]) },
    ]);
    const [west, south, east, north] = mapExtent(map)!;
    const [w, s] = worldMercatorToLonLat(origin[0] - 1200, origin[1] - 600);
    const [e, n] = worldMercatorToLonLat(origin[0] + 1200, origin[1] + 600);
    expect([west, south, east, north].map((v) => v.toFixed(6))).toEqual([w, s, e, n].map((v) => v.toFixed(6)));
  });

  test("a map with no origin or no vertices has none", () => {
    expect(mapExtent({ layerManager: { hasOrigin: false } })).toBeNull();
    expect(mapExtent(fakeMap([0, 0], []))).toBeNull();
  });
});

describe("setBasemap", () => {
  const origin = lonLatToWorldMercator(-87.63, 41.88);
  const dataLayer = () => ({ layerInfo: { id: "input_0", typeLayer: "polygons" }, position: new Float32Array([-500, -500, 500, 500]) });

  test("loads OSM for the map's extent once, under its layers, and hides and shows it after", async () => {
    const map = fakeMap(origin, [dataLayer()]);
    const grammar = { _mapRegistry: new Map([["input_0", map]]) };
    const db = fakeDb();
    const newDb = jest.fn().mockResolvedValue(db);

    await setBasemap(grammar, true, newDb);
    expect(db.loadOsm).toHaveBeenCalledTimes(1);
    const request = db.loadOsm.mock.calls[0][0];
    expect(request.queryArea.bbox).toEqual(mapExtent(map));
    expect(request.autoLoadLayers.layers).toEqual([...BASEMAP_LAYERS]);
    // Each layer by its own OSM type, which autk-map draws below every other; no water here.
    expect(map.loadCollection.mock.calls.map((c: any[]) => [c[0], c[1].type])).toEqual([
      [basemapLayerId("surface"), "surface"],
      [basemapLayerId("parks"), "parks"],
      [basemapLayerId("roads"), "roads"],
    ]);
    expect(map.updateRenderInfo).toHaveBeenCalledWith(basemapLayerId("roads"), { isSkip: false });

    await setBasemap(grammar, false, newDb);
    expect(map.updateRenderInfo).toHaveBeenLastCalledWith(basemapLayerId("roads"), { isSkip: true });
    await setBasemap(grammar, true, newDb);
    expect(map.loadCollection).toHaveBeenCalledTimes(3);
    expect(db.loadOsm).toHaveBeenCalledTimes(1);
  });

  test("a map drawn again over the same extent reuses what was loaded", async () => {
    const db = fakeDb();
    const newDb = jest.fn().mockResolvedValue(db);
    await setBasemap({ _mapRegistry: new Map([["input_0", fakeMap(origin, [dataLayer()])]]) }, true, newDb);
    await setBasemap({ _mapRegistry: new Map([["input_0", fakeMap(origin, [dataLayer()])]]) }, true, newDb);
    expect(db.loadOsm).toHaveBeenCalledTimes(1);
  });

  test("a failed load is not kept, so the next try asks again", async () => {
    const broken = { ...fakeDb(), loadOsm: jest.fn().mockRejectedValue(new Error("Overpass timed out")) };
    const grammar = { _mapRegistry: new Map([["input_0", fakeMap(origin, [dataLayer()])]]) };
    await expect(setBasemap(grammar, true, jest.fn().mockResolvedValue(broken))).rejects.toThrow("Overpass timed out");
    const db = fakeDb();
    await setBasemap(grammar, true, jest.fn().mockResolvedValue(db));
    expect(db.loadOsm).toHaveBeenCalledTimes(1);
  });
});
