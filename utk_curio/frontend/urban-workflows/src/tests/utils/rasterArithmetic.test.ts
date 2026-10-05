/**
 * Raster arithmetic in Curio's Autark adapter (#662, step 8): a comparison of
 * two rasters is the comparison minus the reference, cell by cell, on one
 * grid, and two grids that differ are refused with both named. Compare
 * Scenarios' Difference (step 9) draws its result.
 */
import { describeGrid, gridDifferences, subtractRasters } from "../../utils/raster/rasterArithmetic";
import type { RasterCollection, RasterGrid } from "../../utils/raster/rasterWire";

const GRID: RasterGrid = {
  crs: "EPSG:32616", width: 3, height: 2, originX: 447000, originY: 4637000, resX: 30, resY: -30,
};

function raster(values: Record<string, Array<number | null>>, grid: RasterGrid = GRID): RasterCollection {
  const properties: Record<string, unknown> = {
    rasterResX: grid.width,
    rasterResY: grid.height,
    bands: Object.keys(values).map((id) => ({ id, label: id })),
  };
  for (const [id, cells] of Object.entries(values)) {
    properties[id] = Float32Array.from(cells, (v) => (v === null ? NaN : v));
  }
  return {
    type: "FeatureCollection",
    bbox: [-9785700, 5110100, -9785610, 5110160],
    grid,
    features: [{ type: "Feature", geometry: null, properties: properties as any }],
  };
}

const cells = (collection: RasterCollection, band = "band_1") =>
  Array.from(collection.features[0].properties[band] as Float32Array, (v) => (Number.isNaN(v) ? null : v));

describe("subtractRasters", () => {
  test("the result is the comparison minus the reference: positive where the comparison is higher", () => {
    const result = subtractRasters(
      { name: "No NbS", collection: raster({ band_1: [1, 2, 3, 4, 5, 6] }) },
      { name: "NbS", collection: raster({ band_1: [1, 5, 1, 4.5, 15, 0] }) },
    );
    if (!("collection" in result)) throw new Error(result.refused);
    expect(cells(result.collection)).toEqual([0, 3, -2, 0.5, 10, -6]);
  });

  test("swapping the two flips every sign", () => {
    const a = { name: "A", collection: raster({ band_1: [1, 2, 3, 4, 5, 6] }) };
    const b = { name: "B", collection: raster({ band_1: [6, 5, 4, 3, 2, 1] }) };
    const ab = subtractRasters(a, b);
    const ba = subtractRasters(b, a);
    if (!("collection" in ab) || !("collection" in ba)) throw new Error("refused");
    expect(cells(ab.collection)).toEqual([5, 3, 1, -1, -3, -5]);
    expect(cells(ba.collection)).toEqual([-5, -3, -1, 1, 3, 5]);
  });

  test("a nodata cell on either side is nodata in the result", () => {
    const result = subtractRasters(
      { name: "A", collection: raster({ band_1: [null, 2, 3, 4, 5, 6] }) },
      { name: "B", collection: raster({ band_1: [1, 2, null, 4, 5, 6] }) },
    );
    if (!("collection" in result)) throw new Error(result.refused);
    expect(cells(result.collection)).toEqual([null, 0, null, 0, 0, 0]);
  });

  test("every band is subtracted, and the result is a raster collection autk-map draws", () => {
    const result = subtractRasters(
      { name: "A", collection: raster({ band_1: [1, 1, 1, 1, 1, 1], band_2: [2, 2, 2, 2, 2, 2] }) },
      { name: "B", collection: raster({ band_1: [3, 3, 3, 3, 3, 3], band_2: [0, 0, 0, 0, 0, 0] }) },
    );
    if (!("collection" in result)) throw new Error(result.refused);
    const { collection } = result;
    expect(cells(collection, "band_1")).toEqual([2, 2, 2, 2, 2, 2]);
    expect(cells(collection, "band_2")).toEqual([-2, -2, -2, -2, -2, -2]);
    // The shape autk-map's loadCollection({type: 'raster', property}) reads.
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.bbox).toHaveLength(4);
    expect(collection.grid).toEqual(GRID);
    expect(collection.features).toHaveLength(1);
    const [feature] = collection.features;
    expect(feature.geometry).toBeNull();
    expect(feature.properties).toMatchObject({
      rasterResX: 3,
      rasterResY: 2,
      bands: [{ id: "band_1", label: "band_1" }, { id: "band_2", label: "band_2" }],
    });
    expect(feature.properties.band_1).toBeInstanceOf(Float32Array);
  });

  test.each<[string, Partial<RasterGrid>]>([
    ["size", { width: 2, height: 3 }],
    ["origin", { originX: 447030 }],
    ["resolution", { resX: 10, resY: -10 }],
    ["CRS", { crs: "EPSG:26916" }],
  ])("grids that differ in %s are refused, naming both", (what, change) => {
    const other = { ...GRID, ...change };
    const result = subtractRasters(
      { name: "Reference depth", collection: raster({ band_1: [1, 2, 3, 4, 5, 6] }) },
      { name: "Comparison depth", collection: raster({ band_1: [1, 2, 3, 4, 5, 6] }, other) },
    );
    expect(result).toEqual({
      refused: `Comparison depth minus Reference depth cannot be computed: their grids differ in ${what}. `
        + `Reference depth is ${describeGrid(GRID)}; Comparison depth is ${describeGrid(other)}. `
        + "Put both on one grid first.",
    });
  });

  test("bands that differ are refused, naming both", () => {
    const result = subtractRasters(
      { name: "A", collection: raster({ band_1: [1, 2, 3, 4, 5, 6] }) },
      { name: "B", collection: raster({ band_1: [1, 2, 3, 4, 5, 6], band_2: [1, 2, 3, 4, 5, 6] }) },
    );
    expect(result).toEqual({
      refused: "B minus A cannot be computed: their bands differ. A has band_1; B has band_1, band_2.",
    });
  });
});

describe("gridDifferences", () => {
  test("the same grid, up to rounding in its coordinates, differs in nothing", () => {
    expect(gridDifferences(GRID, { ...GRID, originX: GRID.originX + 1e-7, crs: "epsg:32616" })).toEqual([]);
  });

  test("names every way two grids differ", () => {
    expect(gridDifferences(GRID, { ...GRID, width: 4, originY: 0, resY: -10, crs: "EPSG:4326" }))
      .toEqual(["size", "origin", "resolution", "CRS"]);
  });

  test("a grid in words", () => {
    expect(describeGrid(GRID)).toBe("3 by 2 cells of 30 by 30 in EPSG:32616 from (447000, 4637000)");
  });
});
