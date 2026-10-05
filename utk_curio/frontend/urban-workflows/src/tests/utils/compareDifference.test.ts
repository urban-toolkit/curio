/**
 * What a Compare Scenarios node's Difference view (#662) draws from the
 * difference, its output: the Autark document that maps a raster or a layer
 * (one layer, colored by a band, a number column or `change`), and the
 * Vega-Lite table that shows a table's.
 */
import {
  CHANGES,
  CHANGE_COLORS,
  differenceMapDoc,
  differenceTableSpec,
  differenceValues,
  isDifference,
  resolveValue,
} from "../../utils/compare/compareDifference";
import { TABLE_COLUMNS } from "../../utils/compare/comparePresets";

const LAYER = {
  names: ["osm_id", "change", "sunlight", "name"],
  columns: [
    { name: "osm_id", role: "quantitative" as const },
    { name: "change", role: "nominal" as const },
    { name: "sunlight", role: "quantitative" as const },
    { name: "name", role: "nominal" as const },
  ],
};

describe("what the map colors the difference by", () => {
  test("a raster's bands", () => {
    expect(differenceValues("raster", { bands: ["band_1", "band_2"] }).map((v) => v.value)).toEqual(["band_1", "band_2"]);
  });

  test("a layer's number columns, but the ids it was joined on, and its change", () => {
    const values = differenceValues("layer", LAYER);
    expect(values.map((v) => [v.value, v.categorical])).toEqual([
      ["sunlight", false],
      ["change", true],
    ]);
  });

  test("the one the node keeps when the difference has it, else its first", () => {
    const values = differenceValues("layer", LAYER);
    expect(resolveValue("change", values)?.value).toBe("change");
    expect(resolveValue("height", values)?.value).toBe("sunlight");
    expect(resolveValue(undefined, [])).toBeUndefined();
  });
});

describe("the Autark document that draws it", () => {
  test("a raster, by a band, from dark purple (lowest) to yellow (highest)", () => {
    const [band] = differenceValues("raster", { bands: ["band_1"] });
    expect(differenceMapDoc("raster", band)).toEqual({
      map: { layerRefs: [{ dataRef: "input_0", getFnv: "band_1", colorMapInterpolator: "interpolateViridis" }] },
    });
  });

  test("a layer, by a number column", () => {
    const [sunlight] = differenceValues("layer", LAYER);
    expect(differenceMapDoc("layer", sunlight)).toEqual({
      map: {
        layerRefs: [{
          dataRef: "input_0",
          getFnv: "sunlight",
          getFnvType: "quantitative",
          colorMapInterpolator: "interpolateViridis",
        }],
      },
    });
  });

  test("a layer, by its change, one color for each", () => {
    const change = differenceValues("layer", LAYER).find((v) => v.value === "change");
    expect(differenceMapDoc("layer", change)).toEqual({
      map: {
        layerRefs: [{
          dataRef: "input_0",
          getFnv: "change",
          getFnvType: "categorical",
          colorMapInterpolator: "schemeTableau10",
          colorMapDomain: ["added", "removed", "changed", "unchanged"],
        }],
      },
    });
  });

  test("a layer with nothing to color by, plain", () => {
    expect(differenceMapDoc("layer", undefined)).toEqual({ map: { layerRefs: [{ dataRef: "input_0" }] } });
  });
});

describe("the table a table's difference is shown as", () => {
  test("its first columns in its order, each row in the color of its change", () => {
    const names = ["osm_id", "change", "a", "b", "c", "d", "e", "f", "g", "h"];
    const spec = differenceTableSpec(names) as any;
    expect(spec.transform[2].fold).toEqual(names.slice(0, TABLE_COLUMNS));
    expect(spec.encoding.x.sort).toEqual(names.slice(0, TABLE_COLUMNS));
    expect(spec.encoding.color).toEqual({
      field: "change",
      type: "nominal",
      title: "Change",
      scale: { domain: [...CHANGES], range: CHANGE_COLORS },
    });
    expect(spec.mark).toEqual({ type: "text", align: "left", tooltip: true });
  });

  test("a column whose name holds a dot is read as one field", () => {
    const spec = differenceTableSpec(["osm_id", "change", "tags.highway"]) as any;
    expect(spec.transform[2].fold).toContain("tags\\.highway");
  });
});

describe("whether the node's output is a difference", () => {
  test("a raster is; a layer or a table is when it has change; a stacked table from a Chart run is not", () => {
    expect(isDifference("raster", [])).toBe(true);
    expect(isDifference("layer", LAYER.names)).toBe(true);
    expect(isDifference("table", ["scenario", "scenario_name", "sunlight"])).toBe(false);
    expect(isDifference("other", ["change"])).toBe(false);
  });
});
