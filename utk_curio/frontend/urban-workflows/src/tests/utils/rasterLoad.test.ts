/**
 * How an Autark node asks autk-db to load a raster (#662, step 8): at the
 * raster's own size, so autk-db never resamples it; with `nearest`, so a class
 * code or a nodata cell is never blended; and in its own CRS, since autk-db
 * reads one it is not told about as EPSG:4326. Past what a map holds, the node
 * says to crop the raster where it is made.
 */
import {
  RASTER_MAX_CELLS,
  RASTER_MAX_SIDE,
  oversizeSentence,
  planForGrid,
  planForMeta,
  type RasterMeta,
} from "../../utils/raster/rasterLoad";

const META: RasterMeta = {
  width: 40,
  height: 30,
  count: 1,
  crs: "EPSG:32616",
  crsWkt: null,
  transform: [30, 0, 447000, 0, -30, 4637000],
  nodata: -9999,
};

describe("planForMeta", () => {
  test("a raster loads at its own size, nearest, in its own CRS", () => {
    expect(planForMeta("input_0", META)).toEqual({
      load: { coordinateFormat: "EPSG:32616", maxRasterCells: 40 * 30, resampleMethod: "nearest" },
      grid: { crs: "EPSG:32616", width: 40, height: 30, originX: 447000, originY: 4637000, resX: 30, resY: -30 },
      cells: 1200,
    });
  });

  test("the largest raster a map holds still loads at its own size", () => {
    const side = Math.sqrt(RASTER_MAX_CELLS);
    const plan = planForMeta("input_0", { ...META, width: side, height: side });
    expect("load" in plan && plan.load.maxRasterCells).toBe(RASTER_MAX_CELLS);
  });

  test("past the cap it is refused, with what to do", () => {
    const plan = planForMeta("flood_depth", { ...META, width: 4097, height: 4096 });
    expect(plan).toEqual({
      refused: `flood_depth is 4097 by 4096 cells, more than an Autark map loads at its own size `
        + `(${RASTER_MAX_CELLS} cells, ${RASTER_MAX_SIDE} on a side). Crop it in the node that makes it, `
        + "for example with a rasterio window read, and run that node again.",
    });
  });

  test("a side longer than a texture holds is refused too", () => {
    const plan = planForMeta("strip", { ...META, width: RASTER_MAX_SIDE + 1, height: 1 });
    expect("refused" in plan && plan.refused).toContain("strip is 8193 by 1 cells");
  });

  test("a raster with no CRS, or one with no EPSG code, cannot be placed", () => {
    expect(planForMeta("input_0", { ...META, crs: null })).toEqual({
      refused: "input_0 has no CRS, so Autark cannot place it. Set one in the node that makes it.",
    });
    expect(planForMeta("input_0", { ...META, crs: null, crsWkt: 'PROJCS["local"]' })).toEqual({
      refused: "input_0 is in a CRS with no EPSG code, so Autark cannot place it. "
        + "Reproject it to an EPSG CRS (rasterio.warp) in the node that makes it.",
    });
  });

  test("a rotated raster is refused", () => {
    expect(planForMeta("input_0", { ...META, transform: [30, 2, 447000, 1, -30, 4637000] })).toEqual({
      refused: "input_0 is rotated, and an Autark map draws only north-up rasters. Warp it to a north-up grid first.",
    });
  });
});

describe("planForGrid", () => {
  test("a collection's grid loads at its own size, nearest, in its CRS", () => {
    const grid = { crs: "epsg:4326", width: 3, height: 2, originX: -87.75, originY: 41.875, resX: 0.03125, resY: -0.015625 };
    expect(planForGrid("input_1", grid)).toEqual({
      load: { coordinateFormat: "EPSG:4326", maxRasterCells: 6, resampleMethod: "nearest" },
      grid,
      cells: 6,
    });
  });

  test("a grid in a CRS with no EPSG code is refused", () => {
    const grid = { crs: "ESRI:102003", width: 3, height: 2, originX: 0, originY: 0, resX: 1, resY: -1 };
    expect(planForGrid("input_1", grid)).toEqual({
      refused: "input_1 is in ESRI:102003, which has no EPSG code, so Autark cannot place it.",
    });
  });
});

test("a raster within the cap is not oversize", () => {
  expect(oversizeSentence("input_0", 4096, 4096)).toBeNull();
  // SCOUT's whole flood grid.
  expect(oversizeSentence("input_0", 2592, 2064)).toBeNull();
  expect(oversizeSentence("input_0", 4097, 4096)).not.toBeNull();
});
