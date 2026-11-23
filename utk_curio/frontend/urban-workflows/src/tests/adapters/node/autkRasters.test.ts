/**
 * A raster on an Autark node (#662, step 8): asked of the sandbox by its
 * artifact, loaded into the database the grammar's run goes on with autk-db's
 * `loadGeoTiff` (at its own size, `nearest`, in its CRS), and drawn by the
 * grammar's map. autk-grammar has no source of raster bytes, so the node
 * hands the grammar one around its data adapter (`wrapDataAdapter`); nothing
 * in Autark changes.
 */
const mockFetchRaster = jest.fn();
jest.mock("../../../services/api", () => ({
  fetchRaster: (...args: any[]) => mockFetchRaster(...args),
}));

import {
  CURIO_RASTER_SOURCE,
  RASTER_EXPORT_MISSING,
  framedRaster,
  loadGeoTiffParams,
  bleedIntoClearCells,
  resolveRasterInputs,
  withRasterSources,
  type CurioRasterSource,
} from "../../../adapters/node/autkRasters";
import cases from "../../../utils/raster/rasterWire.cases.json";
import { RASTER_MAX_CELLS, RASTER_MAX_SIDE } from "../../../utils/raster/rasterLoad";
import { grammarThatRan } from "../../_support/autkGrammarMaps";

const META = {
  width: 40,
  height: 30,
  count: 1,
  crs: "EPSG:32616",
  crsWkt: null,
  transform: [30, 0, 447000, 0, -30, 4637000],
  nodata: -9999,
};

beforeEach(() => mockFetchRaster.mockReset());

const base64Of = (buffer: ArrayBuffer) => Buffer.from(new Uint8Array(buffer)).toString("base64");

describe("resolveRasterInputs", () => {
  test("a Python node's raster is asked for by its artifact, and loads at its own size, nearest, in its CRS", async () => {
    const bytes = new Uint8Array([0x49, 0x49, 42, 0]).buffer;
    mockFetchRaster.mockResolvedValue({ ok: true, bytes, meta: META });

    const resolved = await resolveRasterInputs([
      { outputTableName: "input_0", payload: { artifact: "art-heat", part: 1 } },
    ]);

    expect(mockFetchRaster).toHaveBeenCalledWith("art-heat", {
      part: 1, maxCells: RASTER_MAX_CELLS, maxSide: RASTER_MAX_SIDE,
    });
    expect(resolved.problems).toEqual([]);
    expect(resolved.sources).toHaveLength(1);
    expect(loadGeoTiffParams(resolved.sources[0])).toEqual({
      geotiffArrayBuffer: bytes,
      outputTableName: "input_0",
      coordinateFormat: "EPSG:32616",
      maxRasterCells: 1200,
      resampleMethod: "nearest",
    });
    expect(resolved.sources[0]).toMatchObject({
      type: CURIO_RASTER_SOURCE,
      cells: 1200,
      grid: { crs: "EPSG:32616", width: 40, height: 30, originX: 447000, originY: 4637000, resX: 30, resY: -30 },
    });
  });

  test("a raster too large to load is refused with its size and what to do, and nothing else is fetched", async () => {
    mockFetchRaster.mockResolvedValue({
      ok: false, status: 413, meta: { ...META, width: 5000, height: 5000 }, message: "the raster is 5000 by 5000 cells",
    });
    const resolved = await resolveRasterInputs([{ outputTableName: "depth", payload: { artifact: "art-big" } }]);
    expect(resolved.sources).toEqual([]);
    expect(resolved.unusable).toEqual(["depth"]);
    expect(resolved.problems).toEqual([
      expect.stringMatching(/^depth is 5000 by 5000 cells, more than an Autark map loads at its own size .* Crop it in the node that makes it/),
    ]);
  });

  test("a raster with no CRS is refused, naming it", async () => {
    mockFetchRaster.mockResolvedValue({ ok: true, bytes: new ArrayBuffer(8), meta: { ...META, crs: null } });
    const resolved = await resolveRasterInputs([{ outputTableName: "input_0", payload: { artifact: "art" } }]);
    expect(resolved.problems).toEqual([
      "input_0 has no CRS, so Autark cannot place it. Set one in the node that makes it.",
    ]);
  });

  test("a collection an upstream Autark node handed on is written back to GeoTIFF bytes, nothing fetched", async () => {
    const [c] = cases.cases;
    const resolved = await resolveRasterInputs([{ outputTableName: "heat", payload: { envelope: c.envelope } }]);
    expect(mockFetchRaster).not.toHaveBeenCalled();
    expect(resolved.problems).toEqual([]);
    const [source] = resolved.sources;
    expect(base64Of(source.geotiffArrayBuffer)).toBe(c.geotiff_base64);
    expect(source.load).toEqual({ coordinateFormat: "EPSG:32616", maxRasterCells: 12, resampleMethod: "nearest" });
    expect(source.grid).toEqual(c.grid);
  });

  test("a collection that cannot be read is refused, naming it", async () => {
    const envelope = JSON.parse(JSON.stringify(cases.cases[0].envelope));
    delete envelope.data.grid;
    const resolved = await resolveRasterInputs([{ outputTableName: "heat", payload: { envelope } }]);
    expect(resolved.problems).toEqual(["heat cannot be drawn: it does not say which grid its cells lie on."]);
  });
});

describe("withRasterSources", () => {
  const source: CurioRasterSource = {
    type: CURIO_RASTER_SOURCE,
    outputTableName: "input_0",
    geotiffArrayBuffer: new ArrayBuffer(4),
    load: { coordinateFormat: "EPSG:32616", maxRasterCells: 1200, resampleMethod: "nearest" },
    grid: { crs: "EPSG:32616", width: 40, height: 30, originX: 447000, originY: 4637000, resX: 30, resY: -30 },
    cells: 1200,
  };
  // autk-grammar's data adapter, which the node hands withRasterSources.
  const fakeAdapter = () => {
    const original = jest.fn(async (db: any) => db ?? { made: "by the grammar" });
    return { adapter: { resolveSource: original }, original };
  };
  // What getRaster gives: the raster's own extent and one geometry-less feature.
  const RASTER = {
    type: "FeatureCollection",
    bbox: [-9785700, 5106000, -9781700, 5110000],
    features: [{ type: "Feature", geometry: null, properties: { rasterResX: 40, rasterResY: 30, bands: [] } }],
  };
  // autk-db's getLayer, once a layer with geometry set the workspace extent.
  const STAMPED = { ...RASTER, bbox: [0, 0, 1, 1] };
  const fakeDb = () => ({
    loadGeoTiff: jest.fn().mockResolvedValue({ type: "raster" }),
    getRaster: jest.fn().mockResolvedValue(RASTER),
    getLayer: jest.fn().mockResolvedValue(STAMPED),
  });

  test("a raster source goes into the run's database by loadGeoTiff, with its parameters", async () => {
    const { adapter: grammars, original } = fakeAdapter();
    const db = fakeDb();
    const adapter = withRasterSources(grammars);

    const out = await adapter.resolveSource(db, source);

    expect(out).toBe(db);
    expect(db.loadGeoTiff).toHaveBeenCalledWith({
      geotiffArrayBuffer: source.geotiffArrayBuffer,
      outputTableName: "input_0",
      coordinateFormat: "EPSG:32616",
      maxRasterCells: 1200,
      resampleMethod: "nearest",
    });
    expect(original).not.toHaveBeenCalled();
  });

  test("as the first source, it goes into the database the node hands the run, which the rest of the document loads into", async () => {
    // Read off the module as it is, so a checkout without it fails this case on its own.
    const { runDatabase } = require("../../../adapters/node/autkDbClose") as any;
    const { adapter: grammars, original } = fakeAdapter();
    const db = fakeDb();
    const make = jest.fn().mockResolvedValue(db);
    // As a map node hands the grammar its data adapter: the raster loader
    // around the grammar's, inside the one that hands the run its database.
    const adapter = runDatabase(make).handedTo(withRasterSources(grammars));
    expect(await adapter.resolveSource(undefined, source)).toBe(db);
    expect(db.loadGeoTiff).toHaveBeenCalledTimes(1);
    const geojson = { type: "geojson", outputTableName: "roads", geojsonObject: { type: "FeatureCollection", features: [] } };
    expect(await adapter.resolveSource(db, geojson)).toBe(db);
    expect(original).toHaveBeenCalledWith(db, geojson);
    expect(make).toHaveBeenCalledTimes(1);
  });

  test("every other source is the grammar's to load, as before", async () => {
    const { adapter: grammars, original } = fakeAdapter();
    const adapter = withRasterSources(grammars);
    const geojson = { type: "geojson", outputTableName: "roads", geojsonObject: { type: "FeatureCollection", features: [] } };
    const db = { id: "db" };
    expect(await adapter.resolveSource(db, geojson)).toBe(db);
    expect(original).toHaveBeenCalledWith(db, geojson);
  });

  test("the map reads the raster back by getRaster, at its own extent, outlined", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getLayer = db.getLayer;
    const getRaster = db.getRaster;
    await adapter.resolveSource(db, source);

    const layer = await db.getLayer("input_0");
    expect(getLayer).not.toHaveBeenCalled();
    expect(getRaster).toHaveBeenCalledWith("input_0");
    expect(layer).toEqual(framedRaster(RASTER));
    expect(layer.bbox).toEqual(RASTER.bbox);
    expect(layer.features[1].geometry).not.toBeNull();
  });

  // autk-grammar 5's map reads a raster table with getRaster, not getLayer.
  test("repro: the map's getRaster of a raster Curio loaded is answered with it framed, as it was read after loading", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getRaster = db.getRaster;
    await adapter.resolveSource(db, source);

    const raster = await db.getRaster("input_0");
    expect(raster).toEqual(framedRaster(RASTER));
    expect(raster.bbox).toEqual(RASTER.bbox);
    expect(raster.features[1].geometry).not.toBeNull();
    // Read once, right after loading; the map's read is answered with that.
    expect(getRaster.mock.calls).toEqual([["input_0"]]);
  });

  // loadGeoTiff labels a band by its id. A heatmap's bands are labelled
  // `<aggregateFn>_<table>`, and a map's getFnv `count.noise` finds its band
  // by that label, so the map is served the labels the bands were made with.
  test("repro: a raster's bands keep the labels they were made with, so a getFnv such as count.noise finds its band", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const asLoaded = {
      ...RASTER,
      features: [{
        type: "Feature",
        geometry: null,
        properties: { rasterResX: 40, rasterResY: 30, bands: [{ id: "band_1", label: "band_1" }, { id: "band_2", label: "band_2" }] },
      }],
    };
    db.getRaster.mockResolvedValueOnce(asLoaded);
    const made = [{ id: "band_1", label: "count_noise" }, { id: "band_2", label: "sum_noise" }];
    await adapter.resolveSource(db, { ...source, bands: made });

    const raster = await db.getRaster("input_0");
    expect(raster.features[0].properties.bands).toEqual(made);
    expect(raster.bbox).toEqual(RASTER.bbox);
    expect(raster.features[1].geometry).not.toBeNull();
  });

  test("guard: any other table's getRaster is the database's to answer, with all it was asked", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getRaster = db.getRaster;
    await adapter.resolveSource(db, source);

    // A heatmap, which the grammar's own data adapter builds.
    const heat = { ...RASTER, bbox: [1, 2, 3, 4] };
    getRaster.mockResolvedValueOnce(heat);
    expect(await db.getRaster("noise_density", { a: 1 })).toBe(heat);
    expect(getRaster).toHaveBeenLastCalledWith("noise_density", { a: 1 });
  });

  test("repro: a raster loaded again into the same database is read anew, not answered with the first", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getRaster = db.getRaster;
    await adapter.resolveSource(db, source);
    const again = { ...RASTER, bbox: [-9785600, 5106100, -9781600, 5110100] };
    getRaster.mockResolvedValueOnce(again);
    await adapter.resolveSource(db, source);

    expect(getRaster).toHaveBeenCalledTimes(2);
    expect(await db.getRaster("input_0")).toEqual(framedRaster(again));
    expect(await db.getLayer("input_0")).toEqual(framedRaster(again));
  });

  test("every other table is the database's to answer, with all it was asked", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getLayer = db.getLayer;
    await adapter.resolveSource(db, source);

    expect(await db.getLayer("roads", { a: 1 })).toBe(STAMPED);
    expect(getLayer).toHaveBeenCalledWith("roads", { a: 1 });
  });

  test("a second raster in the same database is served by the same wrapper", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const db = fakeDb();
    const getRaster = db.getRaster;
    await adapter.resolveSource(db, source);
    const wrapped = db.getLayer;
    await adapter.resolveSource(db, { ...source, outputTableName: "input_1" });

    expect(db.getLayer).toBe(wrapped);
    expect(getRaster).toHaveBeenCalledWith("input_1");
    expect(await db.getLayer("input_1")).toEqual(framedRaster(RASTER));
  });

  test("a database with no getRaster is named when the raster is loaded", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const { getRaster: _missing, ...db } = fakeDb() as any;
    await expect(adapter.resolveSource(db, source)).rejects.toThrow(RASTER_EXPORT_MISSING);
  });

  test("two maps loading a raster of the same name at once each draw their own", async () => {
    // autk-db keeps raster cells in one store for the page, keyed by
    // workspace and table: both nodes' input_0 is "autk.input_0".
    const store = new Map<string, any>();
    const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
    const pageDb = (cells: string) => ({
      loadGeoTiff: jest.fn(async () => { await tick(); store.set("autk.input_0", cells); await tick(); }),
      // getRaster queries its table first, then reads the store.
      getRaster: jest.fn(async () => { await tick(); return { ...RASTER, cells: store.get("autk.input_0") }; }),
      getLayer: jest.fn(),
    });
    const heights = pageDb("heights");
    const shadows = pageDb("shadows");
    const first = withRasterSources(fakeAdapter().adapter);
    const second = withRasterSources(fakeAdapter().adapter);

    await Promise.all([
      first.resolveSource(heights, source),
      second.resolveSource(shadows, source),
    ]);

    expect((await heights.getLayer("input_0")).cells).toBe("heights");
    expect((await shadows.getLayer("input_0")).cells).toBe("shadows");
  });

  test("repro: two maps loading a raster of the same name at once each read their own by getRaster too", async () => {
    // The same page-wide store as above: a getRaster that went to it would
    // read whichever raster loaded last.
    const store = new Map<string, any>();
    const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
    const pageDb = (cells: string) => ({
      loadGeoTiff: jest.fn(async () => { await tick(); store.set("autk.input_0", cells); await tick(); }),
      getRaster: jest.fn(async (_table: string) => { await tick(); return { ...RASTER, cells: store.get("autk.input_0") }; }),
      getLayer: jest.fn(),
    });
    const heights = pageDb("heights");
    const shadows = pageDb("shadows");
    const first = withRasterSources(fakeAdapter().adapter);
    const second = withRasterSources(fakeAdapter().adapter);

    await Promise.all([
      first.resolveSource(heights, source),
      second.resolveSource(shadows, source),
    ]);

    expect((await heights.getRaster("input_0")).cells).toBe("heights");
    expect((await shadows.getRaster("input_0")).cells).toBe("shadows");
  });

  test("a raster that fails to load does not hold up the next one", async () => {
    const adapter = withRasterSources(fakeAdapter().adapter);
    const broken = { ...fakeDb(), loadGeoTiff: jest.fn().mockRejectedValue(new Error("bad tiff")) };
    await expect(adapter.resolveSource(broken, source)).rejects.toThrow("bad tiff");
    const db = fakeDb();
    await adapter.resolveSource(db, source);
    expect(await db.getLayer("input_0")).toEqual(framedRaster(RASTER));
  });
});

describe("framedRaster", () => {
  test("keeps the raster as it is and adds an outline of its extent, for autk-map to place it by", () => {
    const raster = {
      type: "FeatureCollection",
      bbox: [10, 20, 30, 50],
      features: [{ type: "Feature", geometry: null, properties: { rasterResX: 2, rasterResY: 2, band_1: new Float32Array(4) } }],
    };
    const framed = framedRaster(raster);
    expect(framed.bbox).toEqual([10, 20, 30, 50]);
    expect(framed.features[0]).toBe(raster.features[0]);
    expect(framed.features[1].geometry).toEqual({
      type: "Polygon",
      coordinates: [[[10, 20], [30, 20], [30, 50], [10, 50], [10, 20]]],
    });
    // The raster handed to it is not changed.
    expect(raster.features).toHaveLength(1);
  });
});

// What replaces recolorRasters: autk-grammar 4.2 colors a raster's cells in its
// scheme itself (`updateColorMap`, with `colorMapCenter` and `colorMapReverse`)
// and takes autk-map's transfer function on a raster layer (`transferFunction`).
// Curio writes that transfer function into every raster layer it draws, and
// keeps #718's edge bleed, run after the grammar's run on the layer the
// grammar's lookup finds (`mapLayer`), whatever its title.
describe("withOpaqueRasters", () => {
  const RASTER = { type: CURIO_RASTER_SOURCE, outputTableName: "input_0" };
  const OPAQUE = { opacityMin: 1, opacityMax: 1 };

  test("repro: a layer of a raster the node loads is drawn with every cell that has a value opaque, as SCOUT draws its tiles", () => {
    const { withOpaqueRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [RASTER, { type: "geojson", outputTableName: "table_osm_roads" }],
      map: { layerRefs: [{ dataRef: "input_0", getFnv: "band_1" }, { dataRef: "table_osm_roads" }] },
    };
    const drawn = withOpaqueRasters(spec);
    expect(drawn.map.layerRefs).toEqual([
      { dataRef: "input_0", getFnv: "band_1", transferFunction: OPAQUE },
      { dataRef: "table_osm_roads" },
    ]);
    expect(drawn.data).toBe(spec.data);
    // The document the node holds is not changed.
    expect(spec.map.layerRefs[0]).toEqual({ dataRef: "input_0", getFnv: "band_1" });
  });

  test("repro: a heatmap the document computes is a raster too", () => {
    const { withOpaqueRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [{ type: "heatmap", outputTableName: "noise_density" }],
      map: { layerRefs: [{ dataRef: "noise_density", colorMapInterpolator: "interpolateReds" }] },
    };
    expect(withOpaqueRasters(spec).map.layerRefs[0].transferFunction).toEqual(OPAQUE);
  });

  test("a GeoTIFF the document loads is a raster too", () => {
    const { withOpaqueRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [{ type: "geotiff", geotiffFileUrl: "docs/examples/data/lst.tif", outputTableName: "lst" }],
      map: { layerRefs: [{ dataRef: "lst", getFnv: "band_24", colorMapInterpolator: "interpolateYlOrRd" }] },
    };
    expect(withOpaqueRasters(spec).map.layerRefs[0].transferFunction).toEqual(OPAQUE);
  });

  test("repro: what a layer writes of the transfer function is kept, and the rest is opaque", () => {
    const { withOpaqueRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [RASTER],
      map: [{ layerRefs: [{ dataRef: "input_0", transferFunction: { opacityMin: 0.2, gamma: 2 } }] }],
    };
    // A list of one map is that map.
    expect(withOpaqueRasters(spec).map[0].layerRefs[0].transferFunction).toEqual({ opacityMin: 0.2, opacityMax: 1, gamma: 2 });
  });

  test("guard: a document that draws no raster is handed on as it is", () => {
    const { withOpaqueRasters } = require("../../../adapters/node/autkRasters");
    const roads = { data: [{ type: "geojson", outputTableName: "roads" }], map: { layerRefs: [{ dataRef: "roads" }] } };
    expect(withOpaqueRasters(roads)).toBe(roads);
    const plot = { data: [RASTER], plot: { dataRef: "input_0", mark: "bar" } };
    expect(withOpaqueRasters(plot)).toBe(plot);
  });
});

// autk-map draws a layer of a base-map type (surface, parks, water, roads) in
// a place of its own under every other layer, a raster included, whatever the
// order a map lists them in, and every raster cell is opaque, so a GeoTIFF
// hid the parks and roads drawn on it (example 36's map drew its temperature
// alone). A table the map lists after a raster is handed on as plain geometry,
// which autk-map draws in the map's order.
describe("withLayersOverRasters", () => {
  const LST = { type: CURIO_RASTER_SOURCE, outputTableName: "lst" };
  const layer = (name: string, layerType?: string, workspace?: string) => ({
    type: "geojson", outputTableName: name, geojsonObject: { type: "FeatureCollection", features: [] },
    ...(layerType ? { layerType } : {}), ...(workspace ? { workspace } : {}),
  });

  test("repro: the parks and roads a map lists after a GeoTIFF are drawn over it, as plain geometry", () => {
    const { withLayersOverRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [LST, layer("table_osm_surface", "surface"), layer("table_osm_parks", "parks"), layer("table_osm_roads", "roads")],
      map: { layerRefs: [
        { dataRef: "table_osm_surface" },
        { dataRef: "lst", getFnv: "band_24" },
        { dataRef: "table_osm_parks", color: "#2ca02c" },
        { dataRef: "table_osm_roads" },
      ] },
    };
    const drawn = withLayersOverRasters(spec);
    expect(drawn.data.map((source: any) => [source.outputTableName, source.layerType])).toEqual([
      ["lst", undefined],
      // Listed before the raster, the surface stays under it, typed.
      ["table_osm_surface", "surface"],
      ["table_osm_parks", undefined],
      ["table_osm_roads", undefined],
    ]);
    expect(drawn.map).toBe(spec.map);
    // The document the node holds is not changed.
    expect(spec.data[2]).toEqual(layer("table_osm_parks", "parks"));
  });

  test("a heatmap the document builds is a raster too, in its map's workspace, and a table no map draws keeps its type", () => {
    const { withLayersOverRasters } = require("../../../adapters/node/autkRasters");
    const spec = {
      data: [
        { type: "heatmap", joinDataRef: "table_osm_parks", outputTableName: "park_access", workspace: "east" },
        layer("table_osm_roads", "roads", "east"),
        layer("table_osm_water", "water"),
      ],
      map: { workspace: "east", layerRefs: [{ dataRef: "park_access" }, { dataRef: "table_osm_roads" }] },
    };
    expect(withLayersOverRasters(spec).data.map((source: any) => source.layerType)).toEqual([undefined, undefined, "water"]);
  });

  test("guard: buildings keep their type, and so does every layer of a map with no raster", () => {
    const { withLayersOverRasters } = require("../../../adapters/node/autkRasters");
    const buildings = {
      data: [LST, layer("table_osm_buildings", "buildings")],
      map: { layerRefs: [{ dataRef: "lst" }, { dataRef: "table_osm_buildings" }] },
    };
    expect(withLayersOverRasters(buildings)).toBe(buildings);
    const streets = {
      data: [layer("table_osm_parks", "parks"), layer("table_osm_roads", "roads")],
      map: { layerRefs: [{ dataRef: "table_osm_parks" }, { dataRef: "table_osm_roads" }] },
    };
    expect(withLayersOverRasters(streets)).toBe(streets);
  });
});

describe("bleedRasterEdges", () => {
  // A map as autk-map keeps it: its layers by id, one raster here whose two
  // cells are a red cell with a value and a cell with no data.
  function rasterMap(layerId: string, typeLayer = "raster") {
    const layer: any = {
      layerInfo: { id: layerId, typeLayer },
      rasterResX: 2,
      rasterResY: 1,
      rasterData: new Float32Array([200, 10, 10, 255, 0, 0, 0, 0]),
      makeLayerDataDirty: jest.fn(),
    };
    const map = {
      layerManager: { searchByLayerId: (id: string) => (id === layerId ? layer : null) },
      requestRender: jest.fn(),
    };
    return { map, layer };
  }

  test("repro: a titled raster's clear cells take a neighbor's color: the grammar's lookup finds the layer under its title", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const { map, layer } = rasterMap("Accumulated shadow (minutes)");
    const spec = { map: { layerRefs: [{ dataRef: "input_0", title: "Accumulated shadow (minutes)", getFnv: "band_1" }] } };
    bleedRasterEdges(grammarThatRan(spec, map), spec);
    expect(Array.from(layer.rasterData)).toEqual([200, 10, 10, 255, 200, 10, 10, 0]);
  });

  test("repro: the cells written in place are marked for the GPU, then the map is asked for a frame", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const { map, layer } = rasterMap("input_0");
    let cellsWhenAsked: number[] = [];
    map.requestRender.mockImplementation(() => { cellsWhenAsked = Array.from(layer.rasterData); });
    const spec = { map: { layerRefs: [{ dataRef: "input_0", colorMapInterpolator: "interpolateReds" }] } };
    bleedRasterEdges(grammarThatRan(spec, map), spec);
    // autk-map uploads a layer's cells only when they are marked, and draws on demand.
    expect(layer.makeLayerDataDirty).toHaveBeenCalled();
    expect(map.requestRender).toHaveBeenCalled();
    expect(layer.makeLayerDataDirty.mock.invocationCallOrder[0]).toBeLessThan(map.requestRender.mock.invocationCallOrder[0]);
    expect(cellsWhenAsked).toEqual([200, 10, 10, 255, 200, 10, 10, 0]);
  });

  test("repro: two maps that draw a raster of one table each bleed their own cells, once", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const first = rasterMap("heat");
    const second = rasterMap("heat");
    const spec = { map: [{ layerRefs: [{ dataRef: "heat" }] }, { workspace: "south", layerRefs: [{ dataRef: "heat" }] }] };
    bleedRasterEdges(grammarThatRan(spec, first.map, second.map), spec);
    for (const { map, layer } of [first, second]) {
      expect(Array.from(layer.rasterData)).toEqual([200, 10, 10, 255, 200, 10, 10, 0]);
      expect(layer.makeLayerDataDirty).toHaveBeenCalledTimes(1);
      expect(map.requestRender).toHaveBeenCalledTimes(1);
    }
  });

  test("repro: two layers of one map that draw one raster under two titles each bleed theirs", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const shaded = rasterMap("Shade");
    const plain = rasterMap("Shade, plain");
    const layers: Record<string, any> = { Shade: shaded.layer, "Shade, plain": plain.layer };
    const map = { layerManager: { searchByLayerId: (id: string) => layers[id] ?? null }, requestRender: jest.fn() };
    const spec = { map: { layerRefs: [{ dataRef: "shade", title: "Shade" }, { dataRef: "shade", title: "Shade, plain" }] } };
    bleedRasterEdges(grammarThatRan(spec, map), spec);
    expect(Array.from(shaded.layer.rasterData)).toEqual([200, 10, 10, 255, 200, 10, 10, 0]);
    expect(Array.from(plain.layer.rasterData)).toEqual([200, 10, 10, 255, 200, 10, 10, 0]);
  });

  test("guard: a layer that is not a raster is left as drawn", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const { map, layer } = rasterMap("buildings", "buildings");
    const spec = { map: { layerRefs: [{ dataRef: "buildings", getFnv: "height" }] } };
    bleedRasterEdges(grammarThatRan(spec, map), spec);
    expect(layer.makeLayerDataDirty).not.toHaveBeenCalled();
    expect(map.requestRender).not.toHaveBeenCalled();
  });

  test("guard: a grammar that drew no map, or has no lookup, is no error", () => {
    const { bleedRasterEdges } = require("../../../adapters/node/autkRasters");
    const spec = { map: { layerRefs: [{ dataRef: "input_0" }] } };
    expect(() => bleedRasterEdges({}, spec)).not.toThrow();
    expect(() => bleedRasterEdges(grammarThatRan(spec), spec)).not.toThrow();
    expect(() => bleedRasterEdges(grammarThatRan({ plot: {} }), { plot: {} })).not.toThrow();
  });
});

describe("bleedIntoClearCells", () => {
  // Four values a cell: red, green, blue, alpha.
  const cell = (rgba: Float32Array, i: number) => Array.from(rgba.slice(i * 4, i * 4 + 4));

  test("a clear region takes the color of the nearest cell with a value, and stays clear", () => {
    // 4 by 1: blue, clear, clear, red.
    const rgba = new Float32Array([0, 0, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255]);
    bleedIntoClearCells(rgba, 4, 1);
    expect(cell(rgba, 1)).toEqual([0, 0, 255, 0]);
    expect(cell(rgba, 2)).toEqual([255, 0, 0, 0]);
    expect(cell(rgba, 0)).toEqual([0, 0, 255, 255]);
    expect(cell(rgba, 3)).toEqual([255, 0, 0, 255]);
  });

  test("it reaches across rows and through a whole clear region", () => {
    // 3 by 3, one green cell in a corner.
    const rgba = new Float32Array(9 * 4);
    rgba.set([0, 255, 0, 255], 0);
    bleedIntoClearCells(rgba, 3, 3);
    for (let i = 1; i < 9; i++) expect(cell(rgba, i)).toEqual([0, 255, 0, 0]);
  });

  test("a raster with no value at all is left as it is", () => {
    const rgba = new Float32Array(4 * 4);
    bleedIntoClearCells(rgba, 2, 2);
    expect(Array.from(rgba).every((v) => v === 0)).toBe(true);
  });
});
