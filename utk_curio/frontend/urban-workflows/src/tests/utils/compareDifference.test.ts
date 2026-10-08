/**
 * What a Compare Scenarios node's Difference view (#662) draws from the
 * difference, its output: the Autark document that maps a raster or a layer
 * (one layer, colored by a band, a number column or `change`), and the
 * Vega-Lite table that shows a table's.
 */
import {
  DIFFERENCE_INTERPOLATOR,
  differenceColorOptions,
  differenceColors,
  CHANGES,
  CHANGE_COLORS,
  differenceMapDoc,
  differenceTableName,
  differenceTableSpec,
  differenceValues,
  isDifference,
  joinKey,
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

  test("the ids rows were joined on are left out by name, wherever they come, or the key the node names", () => {
    const columns = [
      { name: "change", role: "nominal" as const },
      { name: "sunlight", role: "quantitative" as const },
      { name: "segment", role: "quantitative" as const },
      { name: "osm_id", role: "quantitative" as const },
    ];
    const names = columns.map((column) => column.name);
    expect(differenceValues("layer", { names, columns }).map((v) => v.value)).toEqual(["sunlight", "segment", "change"]);
    expect(differenceValues("layer", { names, columns }, "segment").map((v) => v.value)).toEqual(["sunlight", "osm_id", "change"]);
    expect(joinKey(names)).toBe("osm_id");
    expect(joinKey(["building_id", "height"])).toBe("building_id");
    expect(joinKey(["height"], "segment")).toBeUndefined();
  });

  test("the one the node keeps when the difference has it, else its first", () => {
    const values = differenceValues("layer", LAYER);
    expect(resolveValue("change", values)?.value).toBe("change");
    expect(resolveValue("height", values)?.value).toBe("sunlight");
    expect(resolveValue(undefined, [])).toBeUndefined();
  });
});

describe("the table the map reads it as", () => {
  test("what it is colored by, a band or a column, and its change", () => {
    const [band] = differenceValues("raster", { bands: ["band_1"] });
    const [sunlight, change] = differenceValues("layer", LAYER);
    expect(differenceTableName(band)).toBe("band_1_change");
    expect(differenceTableName(sunlight)).toBe("sunlight_change");
    expect(differenceTableName(change)).toBe("change");
    expect(differenceTableName(undefined)).toBe("difference");
  });

  test("a name the map's database can take: letters, digits and _, not starting with a digit", () => {
    const value = (name: string) => ({ value: name, text: name, categorical: false });
    expect(differenceTableName(value("Road sunlight (h)"))).toBe("Road_sunlight__h__change");
    expect(differenceTableName(value("2050 heat"))).toBe("_2050_heat_change");
  });
});

describe("the Autark document that draws it", () => {
  test("a raster, by a band, from dark purple (lowest) to yellow (highest), as a layer", () => {
    const [band] = differenceValues("raster", { bands: ["band_1"] });
    expect(differenceMapDoc(band)).toEqual({
      map: {
        layerRefs: [{
          dataRef: "band_1_change",
          legendTitle: "band_1 change",
          getFnv: "band_1",
          getFnvType: "quantitative",
          colorMapInterpolator: "interpolateViridis",
        }],
      },
    });
  });

  test("its legend is titled with what it is colored by, as written, and change", () => {
    const value = (name: string) => ({ value: name, text: name, categorical: false });
    const title = (doc: any) => doc.map.layerRefs[0].legendTitle;
    expect(title(differenceMapDoc(value("Road sunlight (h)")))).toBe("Road sunlight (h) change");
    expect(title(differenceMapDoc(value("band_2")))).toBe("band_2 change");
    const change = differenceValues("layer", LAYER).find((v) => v.value === "change");
    expect(title(differenceMapDoc(change))).toBe("change");
    expect(title(differenceMapDoc(undefined))).toBeUndefined();
  });

  test("a layer, by a number column, from dark purple (lowest) to yellow (highest)", () => {
    const [sunlight] = differenceValues("layer", LAYER);
    expect(differenceMapDoc(sunlight)).toEqual({
      map: {
        layerRefs: [{
          dataRef: "sunlight_change",
          legendTitle: "sunlight change",
          getFnv: "sunlight",
          getFnvType: "quantitative",
          colorMapInterpolator: "interpolateViridis",
        }],
      },
    });
  });

  test("a map of numbers takes the color scale the node picks, and Viridis for one it does not know", () => {
    const [sunlight] = differenceValues("layer", LAYER);
    const scale = (doc: any) => doc.map.layerRefs[0].colorMapInterpolator;
    expect(scale(differenceMapDoc(sunlight, "interpolateReds"))).toBe("interpolateReds");
    expect(scale(differenceMapDoc(sunlight, "interpolateNope"))).toBe("interpolateViridis");
    expect(differenceColors(undefined).value).toBe(DIFFERENCE_INTERPOLATOR);
  });

  test("an absolute difference's legend says so", () => {
    const band = { value: "band_1", text: "band_1", categorical: false };
    const doc: any = differenceMapDoc(band, "interpolateReds", "raster", true);
    expect(doc.map.layerRefs[0].legendTitle).toBe("band_1 absolute change");
    expect((differenceMapDoc(band) as any).map.layerRefs[0].legendTitle).toBe("band_1 change");
  });

  test("blue, white, red centers a raster's difference on no change, red the more; a layer's cannot take it", () => {
    const band = { value: "band_1", text: "band_1", categorical: false };
    const ref = (doc: any) => doc.map.layerRefs[0];
    expect(ref(differenceMapDoc(band, "interpolateRdBu", "raster"))).toMatchObject({
      colorMapInterpolator: "interpolateRdBu", colorMapCenter: 0, colorMapReverse: true,
    });
    const [sunlight] = differenceValues("layer", LAYER);
    const layer = ref(differenceMapDoc(sunlight, "interpolateRdBu", "layer"));
    expect(layer.colorMapInterpolator).toBe("interpolateViridis");
    expect(layer.colorMapCenter).toBeUndefined();
    expect(differenceColorOptions("layer").map((o) => o.value)).not.toContain("interpolateRdBu");
    expect(differenceColors("interpolateRdBu", "raster").note).toBe("White is no change, red more and blue less, the deeper the more.");
  });

  test("a layer, by its change, one color for each", () => {
    const change = differenceValues("layer", LAYER).find((v) => v.value === "change");
    expect(differenceMapDoc(change)).toEqual({
      map: {
        layerRefs: [{
          dataRef: "change",
          legendTitle: "change",
          getFnv: "change",
          getFnvType: "categorical",
          colorMapInterpolator: "schemeTableau10",
          colorMapDomain: ["added", "removed", "changed", "unchanged"],
        }],
      },
    });
  });

  test("a layer with nothing to color by, plain", () => {
    expect(differenceMapDoc(undefined)).toEqual({ map: { layerRefs: [{ dataRef: "difference" }] } });
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
