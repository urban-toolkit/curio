/**
 * What a Compare Scenarios node's Difference view (#662) shows of the
 * difference, its output: the Vega-Lite table that shows a table's, and
 * whether the output is a difference at all. A raster's or a layer's
 * difference is drawn by an Autark node after the node.
 */
import {
  CHANGES,
  CHANGE_COLORS,
  differenceTableSpec,
  isDifference,
} from "../../utils/compare/compareDifference";
import { TABLE_COLUMNS } from "../../utils/compare/comparePresets";

const LAYER = {
  names: ["osm_id", "change", "sunlight", "name"],
};

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
