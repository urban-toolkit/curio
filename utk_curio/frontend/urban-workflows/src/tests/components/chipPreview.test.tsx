/**
 * What a chip's hover shows (components/editing/widgets/ChipPreview): one
 * preview for a header tag and for the chip in the editor, of what the chip
 * holds, read from the examples the e2e tests open (test_chip_previews_e2e.py).
 *
 * - An input: where it comes from (its box with its swatch, else its node's
 *   title, then the node's type when the two differ), its size and kind, and
 *   its first 5 rows, each column with its dtype and a geometry as its type.
 *   A tuple says how code reads its values, then each part's first 3 rows.
 * - A column: its dtype, its first values, and its range or its distinct
 *   values over the rows read, with the empty ones counted.
 * - The stacked `inputs`: the inputs it stacks and its first rows, which begin
 *   with scenario_name, scenario and __input__; `inputs.<field>` reads like a
 *   column.
 * - A widget, a Parameter, a selection, the scenario chips, a chip with a
 *   problem; and an input not run, stale, failed or being read.
 * - Its caps: 5 rows by 6 columns, cells cut at 24 characters, a tuple's first
 *   3 parts with 3 rows each; numbers with at most 4 decimals, null in grey.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import React from "react";
import { cleanup, render } from "@testing-library/react";
import { ChipPreview, TAG_HOW, type ChipPreviewData } from "../../components/editing/widgets/ChipPreview";
import type { CodeLanguage, InputScope, ReferenceScope } from "../../utils/references/codeReferences";
import { readInputPreview, type InputPreview, type InputSource } from "../../utils/references/inputScope";
import { tableTextColor } from "../../utils/scenarios/scenarioColors";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import {
  EXISTING,
  LOOP_INPUTS,
  LOOP_STATISTICS,
  POOL_INPUT,
  SUMMARY_REF,
  SUMMARY_TUPLE,
  TOWERS_REMOVED,
} from "../_support/chipPreviewFixtures";

afterEach(cleanup);

/** *el*'s text, its white space run together. */
const textOf = (el: Element | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();

/** Each line of the preview, in order: what a reader reads, line by line. */
const linesOf = (root: Element) =>
  Array.from(root.querySelectorAll("[data-preview-line]")).map((line) => textOf(line));

/** The head of the preview: the chip, then where it comes from. */
const headOf = (root: Element) => textOf(root.querySelector("[data-preview-head]"));

/** A table's columns, each [name, dtype], and its rows' cells. */
function tableOf(table: Element) {
  const columns = Array.from(table.querySelectorAll("th")).map((th) => [
    textOf(th.querySelector("[data-column-name]")),
    textOf(th.querySelector("[data-column-dtype]")),
  ]);
  const rows = Array.from(table.querySelectorAll("tbody tr")).map((tr) =>
    Array.from(tr.querySelectorAll("td")).map((td) => textOf(td)),
  );
  return { caption: textOf(table.querySelector("caption")), columns, rows };
}

const tablesOf = (root: Element) => Array.from(root.querySelectorAll("table")).map(tableOf);

const footOf = (root: Element) =>
  Array.from(root.querySelectorAll("[data-preview-foot]")).map((foot) => textOf(foot));

function show(props: {
  inner: string;
  scope: ReferenceScope;
  language?: CodeLanguage;
  data?: ChipPreviewData;
  problem?: string | null;
  tag?: boolean;
}) {
  const { container } = render(
    <ChipPreview
      inner={props.inner}
      scope={props.scope}
      language={props.language ?? "json"}
      data={props.data}
      problem={props.problem}
      tag={props.tag}
    />,
  );
  return container.firstElementChild as HTMLElement;
}

const scopeOf = (inputs: InputScope[], extra: Partial<ReferenceScope> = {}): ReferenceScope => ({
  widgets: [],
  inputs,
  shared: [],
  ...extra,
});

const state = (source: InputSource, preview?: InputPreview) => ({ source, ...(preview ? { preview } : {}) });

// interaction-vega's chart: input_0 from the Data Pool, after Run All.
const POOL_SCOPE: InputScope = {
  slot: 0,
  edge: "pool-chart",
  label: "Data Pool",
  dataType: "geodataframe",
  columns: ["geometry", "accessibility", "neighborhood_name"],
  dtypes: { geometry: "geometry", accessibility: "float64", neighborhood_name: "str" },
  scenario: { name: "Data Pool", color: "#8a8f98" },
};
const POOL_SOURCE: InputSource = { title: "Data Pool", status: "done" };

// Example 26's join: input_1 is Summarize's tuple.
const JOIN_INPUTS: InputScope[] = [
  { slot: 0, edge: "e0", label: "Data Loading", dataType: "geodataframe" },
  { slot: 1, edge: "e1", label: "Python Computation", dataType: "outputs", columns: [], dtypes: {}, layers: [], tuple: 2 },
  { slot: 2, edge: "e2", label: "Data Loading", dataType: "geodataframe" },
];
const SUMMARY_SOURCE: InputSource = { title: "Summarize", type: "Python Computation", status: "done" };

// Chicago Loop's chart: both inputs from a box, fed by "Shadow over the ground".
const SHADOW_NOT_RUN: InputSource = { title: "Shadow over the ground", type: "Raster Calculator", status: "not-run" };
const SHADOW_DONE: InputSource = { ...SHADOW_NOT_RUN, status: "done" };

let poolPreview: InputPreview;
let tuplePreview: InputPreview;
let loopPreviews: InputPreview[];

beforeAll(async () => {
  poolPreview = await readInputPreview(POOL_INPUT);
  mockFetchPreviewData.mockResolvedValue(SUMMARY_TUPLE);
  tuplePreview = await readInputPreview(SUMMARY_REF);
  loopPreviews = await Promise.all(LOOP_STATISTICS.map((value) => readInputPreview(value)));
});

describe("an input", () => {
  test("interaction-vega's input_0 tag: from the pool, 79 rows of 3 columns in EPSG:3395, its first 5 rows", () => {
    const root = show({
      inner: "input_0",
      scope: scopeOf([POOL_SCOPE]),
      data: { inputs: { 0: state(POOL_SOURCE, poolPreview) } },
      tag: true,
    });
    expect(root.getAttribute("data-chip-preview")).toBe("input");
    expect(headOf(root)).toBe("input_0 from Data Pool");
    expect(linesOf(root)).toEqual(["79 rows × 3 columns · GeoDataFrame, EPSG:3395"]);
    const [table] = tablesOf(root);
    expect(table.columns).toEqual([
      ["geometry", "geometry"],
      ["accessibility", "float64"],
      ["neighborhood_name", "str"],
    ]);
    expect(table.rows).toEqual([
      ["MultiPolygon", "0.3124", "Adams"],
      ["MultiPolygon", "0.3807", "Wallingford"],
      ["MultiPolygon", "0.3982", "Green Lake"],
      ["MultiPolygon", "0.0194", "Sand Point"],
      ["MultiPolygon", "0.711", "Windermere"],
    ]);
    // A header tag ends with how to use it.
    expect(footOf(root)).toEqual(["first 5 of 79 rows", TAG_HOW]);
    expect(TAG_HOW).toBe("Drag into the code, or click to insert it at the cursor");
  });

  test("example 26's input_1 in the join's code: a tuple of 2 values, each part's first 3 rows", () => {
    const root = show({
      inner: "input_1",
      scope: scopeOf(JOIN_INPUTS),
      language: "python",
      data: { inputs: { 1: state(SUMMARY_SOURCE, tuplePreview) } },
    });
    expect(headOf(root)).toBe("input_1 from Summarize · a Python Computation node");
    expect(linesOf(root)).toEqual(["A tuple of 2 values. Read them in code as input_1[0] and input_1[1]."]);
    expect(tablesOf(root)).toEqual([
      {
        caption: "input_1[0] · 3 rows × 2 columns",
        columns: [["sensor", "str"], ["pm25_mean", "float64"]],
        rows: [["sensor_A", "8.0417"], ["sensor_B", "10.0417"], ["sensor_C", "12.0417"]],
      },
      {
        caption: "input_1[1] · 3 rows × 2 columns",
        columns: [["sensor", "str"], ["pm25_peak", "float64"]],
        rows: [["sensor_A", "11"], ["sensor_B", "13"], ["sensor_C", "15"]],
      },
    ]);
    expect(footOf(root)).toEqual([]);
  });

  test("a header tag and an editor chip show the same preview, the tag's with how to use it", () => {
    const props = {
      inner: "input_1",
      scope: scopeOf(JOIN_INPUTS),
      language: "python" as const,
      data: { inputs: { 1: state(SUMMARY_SOURCE, tuplePreview) } },
    };
    const read = (root: Element) => ({ head: headOf(root), lines: linesOf(root), tables: tablesOf(root), foot: footOf(root) });
    const chip = read(show(props));
    cleanup();
    const tag = read(show({ ...props, tag: true }));
    expect(tag).toEqual({ ...chip, foot: [...chip.foot, TAG_HOW] });
    expect(chip.tables).toHaveLength(2);
  });

  test("a tuple in a spec says what it holds, with no code to read it", () => {
    const root = show({
      inner: "input_1",
      scope: scopeOf(JOIN_INPUTS),
      language: "json",
      data: { inputs: { 1: state(SUMMARY_SOURCE, tuplePreview) } },
    });
    expect(linesOf(root)).toEqual(["A tuple of 2 values."]);
  });

  test("a tuple's first 3 parts, a value as itself, then how many more", () => {
    const table = (tuplePreview as Extract<InputPreview, { kind: "tuple" }>).parts[0];
    const preview: InputPreview = {
      kind: "tuple",
      size: 5,
      parts: [table, { value: 3, dataType: "int" }, table, table, table],
    };
    const root = show({
      inner: "input_1",
      scope: scopeOf(JOIN_INPUTS),
      language: "python",
      data: { inputs: { 1: state(SUMMARY_SOURCE, preview) } },
    });
    expect(linesOf(root)).toEqual([
      "A tuple of 5 values. Read them in code as input_1[0], input_1[1], input_1[2], input_1[3] and input_1[4].",
      "input_1[1] = 3",
    ]);
    expect(tablesOf(root).map((t) => t.caption)).toEqual([
      "input_1[0] · 3 rows × 2 columns",
      "input_1[2] · 3 rows × 2 columns",
    ]);
    expect(footOf(root)).toEqual(["first 3 of 5 values"]);
  });

  test("from a scenario box: the box with its swatch, then the node's title", () => {
    const root = show({
      inner: "input_0",
      scope: scopeOf(LOOP_INPUTS),
      data: { inputs: { 0: state(SHADOW_DONE, loopPreviews[0]) } },
    });
    expect(headOf(root)).toBe("input_0 from Existing · Shadow over the ground");
    const swatch = root.querySelector("[data-preview-head] [data-swatch]");
    expect(swatch?.getAttribute("data-swatch")).toBe("#2a9d8f");
    expect(linesOf(root)).toEqual(["1 row × 5 columns · DataFrame"]);
    expect(tablesOf(root)[0].rows).toEqual([["2.31", "1.84", "0", "9.8", "1.2"]]);
  });

  test("not run: the source, and which node to run", () => {
    const root = show({
      inner: "input_0",
      scope: scopeOf(LOOP_INPUTS),
      data: { inputs: { 0: state(SHADOW_NOT_RUN) } },
      tag: true,
    });
    expect(headOf(root)).toBe("input_0 from Existing · Shadow over the ground");
    expect(linesOf(root)).toEqual(["Not run yet. Run Shadow over the ground to see its rows."]);
    expect(root.querySelector("table")).toBeNull();
    expect(footOf(root)).toEqual([TAG_HOW]);
  });

  test("stale: the last rows, under what says they are from an older run", () => {
    const root = show({
      inner: "input_1",
      scope: scopeOf(JOIN_INPUTS),
      language: "python",
      data: { inputs: { 1: state({ ...SUMMARY_SOURCE, status: "stale" }, tuplePreview) } },
    });
    expect(linesOf(root)).toEqual([
      "From the last run of Summarize, which has changed since",
      "A tuple of 2 values. Read them in code as input_1[0] and input_1[1].",
    ]);
    expect(tablesOf(root)).toHaveLength(2);
  });

  test("errored: the node that feeds it failed, whatever it held", () => {
    const root = show({
      inner: "input_0",
      scope: scopeOf([POOL_SCOPE]),
      data: { inputs: { 0: state({ ...POOL_SOURCE, status: "errored" }, poolPreview) } },
    });
    expect(linesOf(root)).toEqual(["The node that feeds input_0 failed."]);
    expect(root.querySelector("table")).toBeNull();
  });

  test("reading: run, and not read yet", () => {
    const root = show({ inner: "input_0", scope: scopeOf([POOL_SCOPE]), data: { inputs: { 0: state(POOL_SOURCE) } } });
    expect(linesOf(root)).toEqual(["Reading input_0..."]);
  });

  test("a read that failed says so", () => {
    const root = show({
      inner: "input_0",
      scope: scopeOf([POOL_SCOPE]),
      data: { inputs: { 0: state(POOL_SOURCE, { kind: "unreadable" }) } },
    });
    expect(linesOf(root)).toEqual(["Curio could not read input_0."]);
  });

  test("a value shows itself, a raster says what it is, a JSON list its first items, nothing says so", () => {
    const source: InputSource = { title: "Settings", type: "Python Computation", status: "done" };
    const lines = (preview: InputPreview) => {
      const root = show({ inner: "input_0", scope: scopeOf([{ slot: 0 }]), data: { inputs: { 0: state(source, preview) } } });
      const read = { lines: linesOf(root), foot: footOf(root) };
      cleanup();
      return read;
    };
    expect(lines({ kind: "value", dataType: "float", value: 2.123456 })).toEqual({ lines: ["A number: 2.1235"], foot: [] });
    expect(lines({ kind: "value", dataType: "str", value: "winter" })).toEqual({ lines: ["A text: winter"], foot: [] });
    expect(lines({ kind: "value", dataType: "bool", value: false })).toEqual({ lines: ["True or false: false"], foot: [] });
    expect(lines({ kind: "raster" })).toEqual({ lines: ["A raster"], foot: [] });
    expect(
      lines({
        kind: "json",
        shape: "list",
        total: 12,
        items: [0, 10, 20, 30, 40].map((value, i) => ({ key: String(i), value })),
      }),
    ).toEqual({ lines: ["A list of 12 items", "0: 0", "1: 10", "2: 20", "3: 30", "4: 40"], foot: ["first 5 of 12 items"] });
    expect(
      lines({ kind: "json", shape: "dict", total: 2, items: [{ key: "season", value: "winter" }, { key: "hours", value: 6 }] }),
    ).toEqual({ lines: ["A dict of 2 keys", "season: winter", "hours: 6"], foot: [] });
    expect(lines({ kind: "empty" })).toEqual({ lines: ["It holds no value."], foot: [] });
  });

  test("layers: how many, then each layer's feature count, geometry type and first 3 rows", () => {
    const table = (rows: number, type: string, column: string) => ({
      frameType: "geodataframe" as const,
      columns: [column],
      dtypes: {},
      rows: Array.from({ length: Math.min(rows, 5) }, (_, i) => ({ [column]: i })),
      totalRows: rows,
      readRows: rows,
      summaries: {},
      crs: null,
      geometryType: type,
    });
    const preview: InputPreview = {
      kind: "layers",
      layers: [
        { name: "table_osm_roads", table: table(1234, "LineString", "highway") },
        { name: "table_osm_buildings", table: table(2, "Polygon", "height") },
        { name: "table_osm_parks", table: table(7, "MultiPolygon", "leisure") },
        { name: "table_osm_water", table: table(3, "Polygon", "natural") },
      ],
    };
    const root = show({
      inner: "input_0",
      scope: scopeOf([{ slot: 0, label: "Autark" }]),
      data: { inputs: { 0: state({ title: "Load OSM", type: "Autark", status: "done" }, preview) } },
    });
    expect(headOf(root)).toBe("input_0 from Load OSM · an Autark node");
    expect(linesOf(root)).toEqual(["4 layers"]);
    const tables = tablesOf(root);
    expect(tables.map((t) => t.caption)).toEqual([
      "table_osm_roads · 1,234 features, LineString",
      "table_osm_buildings · 2 features, Polygon",
      "table_osm_parks · 7 features, MultiPolygon",
    ]);
    expect(tables[0].rows).toEqual([["0"], ["1"], ["2"]]);
    expect(footOf(root)).toEqual(["first 3 of 4 layers"]);

    cleanup();
    const layer = show({
      inner: "input_0:table_osm_roads",
      scope: scopeOf([{ slot: 0, label: "Autark" }]),
      data: { inputs: { 0: state({ title: "Load OSM", type: "Autark", status: "done" }, preview) } },
    });
    expect(layer.getAttribute("data-chip-preview")).toBe("layer");
    expect(headOf(layer)).toBe("table_osm_roads layer of input_0");
    expect(linesOf(layer)).toEqual(["1,234 features · LineString"]);
    expect(tablesOf(layer)[0].rows).toEqual([["0"], ["1"], ["2"]]);
    expect(footOf(layer)).toEqual(["first 3 of 1,234 rows"]);
  });
});

describe("caps and formatting", () => {
  test("5 rows by 6 columns, cells cut at 24 characters, null in grey, numbers with at most 4 decimals", () => {
    const columns = ["name", "a", "b", "c", "d", "e", "f", "g", "h"];
    const preview: InputPreview = {
      kind: "frame",
      table: {
        frameType: "dataframe",
        columns,
        dtypes: { name: "str", a: "float64" },
        rows: Array.from({ length: 5 }, (_, i) => ({
          name: i === 0 ? "A neighborhood name longer than the cut" : `row ${i}`,
          a: i === 1 ? null : i + 0.123456,
          b: 1, c: 2, d: 3, e: 4, f: 5, g: 6, h: 7,
        })),
        totalRows: 73,
        readRows: 73,
        summaries: {},
      },
    };
    const root = show({
      inner: "input_0",
      scope: scopeOf([{ slot: 0, label: "Data Loading" }]),
      data: { inputs: { 0: state({ title: "Data Loading", status: "done" }, preview) } },
    });
    expect(linesOf(root)).toEqual(["73 rows × 9 columns · DataFrame"]);
    const [table] = tablesOf(root);
    expect(table.columns.map(([name]) => name)).toEqual(["name", "a", "b", "c", "d", "e"]);
    expect(table.rows[0][0]).toBe("A neighborhood name lon…");
    expect(table.rows[0][0]).toHaveLength(24);
    expect(table.rows[0][1]).toBe("0.1235");
    expect(table.rows[1][1]).toBe("null");
    expect(root.querySelector("tbody tr:nth-child(2) td:nth-child(2) [data-null]")).not.toBeNull();
    expect(table.rows).toHaveLength(5);
    expect(footOf(root)).toEqual(["first 5 of 73 rows, 6 of 9 columns"]);
  });
});

describe("a column", () => {
  test("interaction-vega's accessibility: its dtype, first values, and range over all 79 rows", () => {
    const root = show({
      inner: "input_0.accessibility",
      scope: scopeOf([POOL_SCOPE]),
      data: { inputs: { 0: state(POOL_SOURCE, poolPreview) } },
      tag: true,
    });
    expect(root.getAttribute("data-chip-preview")).toBe("column");
    expect(headOf(root)).toBe("accessibility column of input_0 · float64");
    expect(linesOf(root)).toEqual([
      "0.3124, 0.3807, 0.3982, 0.0194, 0.711, ...",
      "range 0 to 1 in all 79 rows · no empty values",
    ]);
    expect(footOf(root)).toEqual([TAG_HOW]);
  });

  test("text: its distinct values, and a column cut to the first 100 rows says so", () => {
    const names = Array.from({ length: 100 }, (_, i) => (i < 3 ? null : `zip ${i % 12}`));
    const preview: InputPreview = {
      kind: "frame",
      table: {
        frameType: "dataframe",
        columns: ["zip"],
        dtypes: { zip: "str" },
        rows: names.slice(0, 5).map((zip) => ({ zip })),
        totalRows: 2500,
        readRows: 100,
        summaries: { zip: { empty: 3, distinct: Array.from({ length: 12 }, (_, i) => `zip ${i}`) } },
      },
    };
    const root = show({
      inner: "input_0.zip",
      scope: scopeOf([{ slot: 0, label: "Data Loading", columns: ["zip"], dtypes: { zip: "str" } }]),
      data: { inputs: { 0: state({ title: "ZIP codes", type: "Data Loading", status: "done" }, preview) } },
    });
    expect(headOf(root)).toBe("zip column of input_0 · str");
    expect(linesOf(root)).toEqual([
      "null, null, null, zip 3, zip 4, ...",
      "12 distinct values in the first 100 rows · 3 empty values",
    ]);
  });

  test("not run: its type and values come after a run", () => {
    const root = show({
      inner: "input_0.mean",
      scope: scopeOf(LOOP_INPUTS),
      data: { inputs: { 0: state(SHADOW_NOT_RUN) } },
    });
    expect(headOf(root)).toBe("mean column of input_0");
    expect(linesOf(root)).toEqual(["Not run yet. Its type and values come after a run of Shadow over the ground."]);
  });
});

describe("the stacked inputs", () => {
  const loopRun = () => ({
    inputs: { 0: state(SHADOW_DONE, loopPreviews[0]), 1: state(SHADOW_DONE, loopPreviews[1]) },
  });

  test("Chicago Loop, run: the inputs it stacks, its first rows from scenario_name with swatches, 6 of its 8 fields", () => {
    const root = show({ inner: "inputs", scope: scopeOf(LOOP_INPUTS), data: loopRun() });
    expect(root.getAttribute("data-chip-preview")).toBe("dataset");
    expect(headOf(root)).toBe("inputs input_0 and input_1, stacked · 2 rows × 8 fields");
    const [table] = tablesOf(root);
    expect(table.columns).toEqual([
      ["scenario_name", "str"],
      ["scenario", "str"],
      ["__input__", "int64"],
      ["mean", "float64"],
      ["median", "float64"],
      ["min", "float64"],
    ]);
    expect(table.rows).toEqual([
      ["Existing", "existing", "0", "2.31", "1.84", "0"],
      ["Towers removed", "towers-removed", "1", "1.97", "1.52", "0"],
    ]);
    const swatches = Array.from(root.querySelectorAll("tbody [data-swatch]")).map((el) => el.getAttribute("data-swatch"));
    expect(swatches).toEqual(["#2a9d8f", "#e76f51"]);
    expect(footOf(root)).toEqual(["2 rows, 6 of 8 fields"]);
  });

  test("Chicago Loop, as it opens: not run, and the fields its rows begin with", () => {
    const root = show({
      inner: "inputs",
      scope: scopeOf(LOOP_INPUTS),
      data: { inputs: { 0: state(SHADOW_NOT_RUN), 1: state(SHADOW_NOT_RUN) } },
    });
    expect(headOf(root)).toBe("inputs input_0 and input_1, stacked");
    expect(linesOf(root)).toEqual([
      "Not run yet. Run Shadow over the ground to see its rows.",
      "Its rows begin with scenario_name, scenario and __input__.",
    ]);
    expect(root.querySelector("table")).toBeNull();
  });

  test("an input it cannot stack: why, as the chart says it", () => {
    const root = show({
      inner: "inputs",
      scope: scopeOf([LOOP_INPUTS[0], { ...LOOP_INPUTS[1], scenario: TOWERS_REMOVED }]),
      data: { inputs: { 0: state(SHADOW_DONE, loopPreviews[0]), 1: state(SUMMARY_SOURCE, tuplePreview) } },
    });
    expect(linesOf(root)).toEqual([
      'The dataset "inputs": input_1 (Towers removed) carries 2 tables. Connect a node that returns one table, '
        + "or pick the table to compare in a node between them.",
    ]);
  });

  test("inputs.mean reads like a column over the stacked rows", () => {
    const root = show({ inner: "inputs.mean", scope: scopeOf(LOOP_INPUTS), data: loopRun() });
    expect(root.getAttribute("data-chip-preview")).toBe("stacked");
    expect(headOf(root)).toBe("mean field of inputs · float64");
    expect(linesOf(root)).toEqual(["2.31, 1.97", "range 1.97 to 2.31 in all 2 rows · no empty values"]);
  });

  test("inputs.scenario_name: each box's name, with its swatch", () => {
    const root = show({ inner: "inputs.scenario_name", scope: scopeOf(LOOP_INPUTS), data: loopRun() });
    expect(headOf(root)).toBe("scenario_name field of inputs · str");
    expect(linesOf(root)).toEqual(["Existing, Towers removed", "2 distinct values in all 2 rows · no empty values"]);
  });
});

describe("a widget and a Parameter", () => {
  const combine: WidgetDef = {
    name: "combine",
    type: "choice",
    label: "Combine",
    default: "mean",
    value: "mean",
    options: { choices: ["mean", "sum", "median", "min", "max", "count"] },
  };
  const zoom: WidgetDef = { name: "zoom", type: "number", label: "Zoom level", default: 16, options: { min: 1, max: 20, step: 1 } };
  const season: WidgetDef = {
    name: "season",
    type: "choice",
    label: "Season",
    default: "summer",
    options: { choices: ["spring", "summer", "winter"], display: "radio" },
  };

  test("Chicago Loop's combine: its control, its value, its choices, and what it writes", () => {
    const root = show({ inner: "combine", scope: scopeOf(LOOP_INPUTS, { widgets: [combine] }), tag: true });
    expect(root.getAttribute("data-chip-preview")).toBe("widget");
    expect(headOf(root)).toBe("combine a Choice widget");
    expect(linesOf(root)).toEqual([
      "Choice: mean",
      "Choices: mean, sum, median, min, max, count",
      'writes "mean"',
    ]);
    expect(footOf(root)).toEqual([TAG_HOW]);
  });

  test("a number: its range and step, and in Python what it writes", () => {
    const root = show({ inner: "zoom", scope: scopeOf([], { widgets: [zoom] }), language: "python" });
    expect(linesOf(root)).toEqual(["Number: 16", "Range 1 to 20, step 1", "writes 16"]);
  });

  test("Chicago Loop's Season Parameter: its node, how many nodes read it, what it writes", () => {
    const root = show({
      inner: "@season",
      scope: scopeOf(LOOP_INPUTS, { shared: [season] }),
      language: "python",
      data: { parameters: { season: { node: "Season", readers: 2 } } },
    });
    expect(root.getAttribute("data-chip-preview")).toBe("shared");
    expect(headOf(root)).toBe("@season from the Parameter node Season");
    expect(linesOf(root)).toEqual([
      "Choice: summer",
      "Choices: spring, summer, winter",
      'writes "summer"',
      "Read by 2 nodes",
    ]);
  });
});

describe("a selection", () => {
  const picked = { name: "picked", node: "zip-bars", column: "zip", ids: ["60601", "60602", "60603", "60604", "60605", "60606", "60607"] };

  test("its view, column and count, its first 5 ids, and the selected rows' first 3 once the view has drawn", () => {
    const root = show({
      inner: "selection picked",
      scope: scopeOf([], { selections: [picked] }),
      language: "python",
      data: {
        selections: {
          picked: {
            view: "ZIP code bars",
            rows: {
              columns: ["zip", "count"],
              rows: [{ zip: "60601", count: 12 }, { zip: "60602", count: 7 }, { zip: "60603", count: 3 }],
            },
          },
        },
      },
    });
    expect(root.getAttribute("data-chip-preview")).toBe("selection");
    expect(headOf(root)).toBe("selection picked from the view ZIP code bars");
    expect(linesOf(root)).toEqual(["7 zip values selected", "60601, 60602, 60603, 60604, 60605, ..."]);
    expect(tablesOf(root)[0].rows).toEqual([["60601", "12"], ["60602", "7"], ["60603", "3"]]);
  });

  test("before the view has drawn, the ids alone", () => {
    const root = show({
      inner: "selection picked",
      scope: scopeOf([], { selections: [picked] }),
      data: { selections: { picked: { view: "ZIP code bars" } } },
    });
    expect(linesOf(root)).toEqual([
      "7 zip values selected",
      "60601, 60602, 60603, 60604, 60605, ...",
      "The selected rows show once ZIP code bars has drawn.",
    ]);
    expect(root.querySelector("table")).toBeNull();
  });
});

describe("the scenario chips", () => {
  test("Chicago Loop's colors: each box's swatch, name and hex, and the scale it writes", () => {
    const root = show({ inner: "scenario colors", scope: scopeOf(LOOP_INPUTS) });
    expect(root.getAttribute("data-chip-preview")).toBe("scenario");
    expect(headOf(root)).toBe("scenario colors a color scale");
    expect(linesOf(root)).toEqual([
      "Existing #2a9d8f",
      "Towers removed #e76f51",
      'writes {"domain": ["Existing", "Towers removed"], "range": ["#2a9d8f", "#e76f51"]}',
    ]);
    const swatches = Array.from(root.querySelectorAll("[data-swatch]")).map((el) => el.getAttribute("data-swatch"));
    expect(swatches).toEqual(["#2a9d8f", "#e76f51"]);
  });

  test("text_colors: the same boxes in the shades a text mark reads in", () => {
    const root = show({ inner: "scenario text_colors", scope: scopeOf(LOOP_INPUTS) });
    const shades = [tableTextColor(EXISTING.color), tableTextColor(TOWERS_REMOVED.color)];
    expect(headOf(root)).toBe("scenario text_colors a color scale for a text mark");
    expect(linesOf(root).slice(0, 2)).toEqual([`Existing ${shades[0]}`, `Towers removed ${shades[1]}`]);
  });

  test("order: the names in the order of their boxes", () => {
    const root = show({ inner: "scenario order", scope: scopeOf(LOOP_INPUTS) });
    expect(headOf(root)).toBe("scenario order the names in order");
    expect(linesOf(root)).toEqual(["Existing", "Towers removed", 'writes ["Existing", "Towers removed"]']);
  });

  test("an input's color: its box and the color it writes", () => {
    const root = show({ inner: "scenario input_1", scope: scopeOf(LOOP_INPUTS) });
    expect(headOf(root)).toBe("scenario input_1 the color of Towers removed");
    expect(linesOf(root)).toEqual(["Towers removed #e76f51", "the box input_1 comes from", 'writes "#e76f51"']);
  });
});

describe("a chip with a problem", () => {
  test("shows the problem, as its hover does today", () => {
    const problem = "[!! input_3 !!]: this node has no input_3. Its inputs are input_0, input_1 and input_2.";
    const root = show({ inner: "input_3", scope: scopeOf(JOIN_INPUTS), language: "python", problem });
    expect(root.getAttribute("data-chip-preview")).toBe("problem");
    expect(headOf(root)).toBe("input_3");
    expect(linesOf(root)).toEqual([problem]);
  });
});
