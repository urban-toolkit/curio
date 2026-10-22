/**
 * What a chip's preview reads, taken from the shipped examples the e2e tests
 * open (test_chip_previews_e2e.py):
 *
 * - example 26's Summarize returns a tuple, each sensor's mean PM2.5 and its
 *   peak, from the example's 36 readings: its join reads it as input_1;
 * - interaction-vega's Data Pool hands its chart input_0, the 79
 *   neighborhoods' normalized accessibility in EPSG:3395, inline;
 * - Chicago Loop's chart reads the shadow statistics of two boxes, Existing
 *   and Towers removed, stacked as `inputs`.
 */
import type { InputScope } from "../../utils/references/codeReferences";

/** Example 26's Summarize, as `/get-preview` sends its tuple: two tables, cut to nothing. */
export const SUMMARY_TUPLE = {
  dataType: "outputs",
  data: [
    {
      dataType: "dataframe",
      data: { sensor: ["sensor_A", "sensor_B", "sensor_C"], pm25_mean: [8.041667, 10.041667, 12.041667] },
      schema: { sensor: "str", pm25_mean: "float64" },
    },
    {
      dataType: "dataframe",
      data: { sensor: ["sensor_A", "sensor_B", "sensor_C"], pm25_peak: [11.0, 13.0, 15.0] },
      schema: { sensor: "str", pm25_peak: "float64" },
    },
  ],
  filename: "several-summary-artifact",
};

/** What example 26's join holds on circle 1: Summarize's artifact. */
export const SUMMARY_REF = { path: "several-summary-artifact", dataType: "outputs" };

/**
 * interaction-vega's 79 neighborhoods: the example's first five, then 74 that
 * stand in for the rest, over the same range (the score is normalized, so its
 * least is 0 and its greatest 1).
 */
export const NEIGHBORHOODS: Array<[string, number]> = [
  ["Adams", 0.3124],
  ["Wallingford", 0.3807],
  ["Green Lake", 0.3982],
  ["Sand Point", 0.0194],
  ["Windermere", 0.711],
  ...Array.from({ length: 74 }, (_, i): [string, number] => [`Neighborhood ${i + 6}`, Number((i / 73).toFixed(4))]),
];

/** The pool's rows as it hands them on: inline, with the flag it adds to each. */
export const POOL_INPUT = {
  dataType: "geodataframe",
  data: {
    type: "FeatureCollection",
    crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::3395" } },
    geometry_name: "geometry",
    features: NEIGHBORHOODS.map(([name, accessibility]) => ({
      type: "Feature",
      geometry: { type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
      properties: { accessibility, neighborhood_name: name, interacted: "0" },
    })),
  },
  schema: { geometry: "geometry", accessibility: "float64", neighborhood_name: "str" },
  filename: "interaction-vega-pool-artifact",
};

/** Chicago Loop's two boxes. */
export const EXISTING = { scenario: "existing", name: "Existing", color: "#2a9d8f", rank: 0 };
export const TOWERS_REMOVED = { scenario: "towers-removed", name: "Towers removed", color: "#e76f51", rank: 1 };

/** The chart's two inputs, as its editor's scope holds them before a run. */
export const LOOP_INPUTS: InputScope[] = [
  { slot: 0, edge: "loop-existing", label: "Raster Calculator", columns: null, scenario: EXISTING },
  { slot: 1, edge: "loop-towers", label: "Raster Calculator", columns: null, scenario: TOWERS_REMOVED },
];

/**
 * The shadow statistics each box's raster calculator returns, one row each.
 * Illustrative numbers, as the mockup's: real ones come from a run of the
 * shadow model, which needs a GPU.
 */
export const LOOP_STATISTICS = [
  { dataType: "dataframe", data: { mean: [2.31], median: [1.84], min: [0], max: [9.8], std: [1.2] },
    schema: { mean: "float64", median: "float64", min: "float64", max: "float64", std: "float64" } },
  { dataType: "dataframe", data: { mean: [1.97], median: [1.52], min: [0], max: [9.1], std: [1.1] },
    schema: { mean: "float64", median: "float64", min: "float64", max: "float64", std: "float64" } },
];
