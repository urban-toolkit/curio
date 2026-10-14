/**
 * A raster on an Autark node (#662, step 8): asked of the sandbox by its
 * artifact, loaded into the grammar's own database with autk-db's
 * `loadGeoTiff` (at its own size, `nearest`, in its CRS), and drawn by the
 * grammar's map. autk-grammar has no GeoTIFF source, so the grammar instance's
 * data adapter is taught one; nothing in Autark changes.
 */
const mockFetchRaster = jest.fn();
jest.mock("../../../services/api", () => ({
  fetchRaster: (...args: any[]) => mockFetchRaster(...args),
}));

import {
  CURIO_RASTER_SOURCE,
  RASTER_ADAPTER_MISSING,
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
  const fakeGrammar = () => {
    const original = jest.fn(async (db: any) => db ?? { made: "by the grammar" });
    return { grammar: { dataAdapter: { resolveSource: original } } as any, original };
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

  test("a raster source goes into the grammar's own database by loadGeoTiff, with its parameters", async () => {
    const { grammar, original } = fakeGrammar();
    const db = fakeDb();
    const newDb = jest.fn();
    withRasterSources(grammar, newDb);

    const out = await grammar.dataAdapter.resolveSource(db, source);

    expect(out).toBe(db);
    expect(db.loadGeoTiff).toHaveBeenCalledWith({
      geotiffArrayBuffer: source.geotiffArrayBuffer,
      outputTableName: "input_0",
      coordinateFormat: "EPSG:32616",
      maxRasterCells: 1200,
      resampleMethod: "nearest",
    });
    expect(newDb).not.toHaveBeenCalled();
    expect(original).not.toHaveBeenCalled();
  });

  test("as the first source, it makes the database the rest of the document loads into", async () => {
    const { grammar } = fakeGrammar();
    const db = fakeDb();
    withRasterSources(grammar, jest.fn().mockResolvedValue(db));
    expect(await grammar.dataAdapter.resolveSource(undefined, source)).toBe(db);
    expect(db.loadGeoTiff).toHaveBeenCalledTimes(1);
  });

  test("every other source is the grammar's to load, as before", async () => {
    const { grammar, original } = fakeGrammar();
    withRasterSources(grammar, jest.fn());
    const geojson = { type: "geojson", outputTableName: "roads", geojsonObject: { type: "FeatureCollection", features: [] } };
    const db = { id: "db" };
    expect(await grammar.dataAdapter.resolveSource(db, geojson)).toBe(db);
    expect(original).toHaveBeenCalledWith(db, geojson);
  });

  test("a grammar build that loads its data some other way is named, not silently undrawn", () => {
    expect(() => withRasterSources({}, jest.fn())).toThrow(RASTER_ADAPTER_MISSING);
    expect(() => withRasterSources({ dataAdapter: {} }, jest.fn())).toThrow(RASTER_ADAPTER_MISSING);
  });

  test("the map reads the raster back by getRaster, at its own extent, outlined", async () => {
    const { grammar } = fakeGrammar();
    const db = fakeDb();
    const getLayer = db.getLayer;
    withRasterSources(grammar, jest.fn());
    await grammar.dataAdapter.resolveSource(db, source);

    const layer = await db.getLayer("input_0");
    expect(getLayer).not.toHaveBeenCalled();
    expect(db.getRaster).toHaveBeenCalledWith("input_0");
    expect(layer).toEqual(framedRaster(RASTER));
    expect(layer.bbox).toEqual(RASTER.bbox);
    expect(layer.features[1].geometry).not.toBeNull();
  });

  test("every other table is the database's to answer, with all it was asked", async () => {
    const { grammar } = fakeGrammar();
    const db = fakeDb();
    const getLayer = db.getLayer;
    withRasterSources(grammar, jest.fn());
    await grammar.dataAdapter.resolveSource(db, source);

    expect(await db.getLayer("roads", { a: 1 })).toBe(STAMPED);
    expect(getLayer).toHaveBeenCalledWith("roads", { a: 1 });
  });

  test("a second raster in the same database is served by the same wrapper", async () => {
    const { grammar } = fakeGrammar();
    const db = fakeDb();
    withRasterSources(grammar, jest.fn());
    await grammar.dataAdapter.resolveSource(db, source);
    const wrapped = db.getLayer;
    await grammar.dataAdapter.resolveSource(db, { ...source, outputTableName: "input_1" });

    expect(db.getLayer).toBe(wrapped);
    expect(db.getRaster).toHaveBeenCalledWith("input_1");
    expect(await db.getLayer("input_1")).toEqual(framedRaster(RASTER));
  });

  test("a database with no getRaster is named when the raster is loaded", async () => {
    const { grammar } = fakeGrammar();
    const { getRaster: _missing, ...db } = fakeDb() as any;
    withRasterSources(grammar, jest.fn());
    await expect(grammar.dataAdapter.resolveSource(db, source)).rejects.toThrow(RASTER_EXPORT_MISSING);
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
    const first = fakeGrammar().grammar;
    const second = fakeGrammar().grammar;
    withRasterSources(first, jest.fn());
    withRasterSources(second, jest.fn());

    await Promise.all([
      first.dataAdapter.resolveSource(heights, source),
      second.dataAdapter.resolveSource(shadows, source),
    ]);

    expect((await heights.getLayer("input_0")).cells).toBe("heights");
    expect((await shadows.getLayer("input_0")).cells).toBe("shadows");
  });

  test("a raster that fails to load does not hold up the next one", async () => {
    const { grammar } = fakeGrammar();
    const broken = { ...fakeDb(), loadGeoTiff: jest.fn().mockRejectedValue(new Error("bad tiff")) };
    withRasterSources(grammar, jest.fn());
    await expect(grammar.dataAdapter.resolveSource(broken, source)).rejects.toThrow("bad tiff");
    const db = fakeDb();
    await grammar.dataAdapter.resolveSource(db, source);
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
