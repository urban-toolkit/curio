/**
 * The single path from an input payload to render-ready rows.
 *
 * The property that matters most here is the *gate*: geometry is attached
 * because the spec draws it, not because the payload happens to be a
 * GeoDataFrame. Shipped dataflows chart a 1.5 MB GeoJSON as a bar chart, and
 * attaching geometry unconditionally would inline all of it into
 * `spec.data.values` and re-ship it through `changeset()` on every brush.
 */
import { injectInputs, prepareVegaInput, prepareVegaInputs, usesNamedDatasets } from "../../utils/vegaInput";
import { readsInputs } from "../../utils/vegaDatasets";
import { resolveReferences } from "../../utils/references/codeReferences";
import { inputScopeFor } from "../../utils/references/inputScope";

jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
}));

const { fetchData } = require("../../services/api");

const polygon = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] };

const geoPayload = {
  type: "FeatureCollection",
  geometry_name: "geometry",
  features: [
    { properties: { zip: "60601", pop: 2746 }, geometry: polygon },
    { properties: { zip: "60602", pop: 8804 }, geometry: polygon },
  ],
};

const framePayload = { zip: { 0: "60601", 1: "60602" }, pop: { 0: 2746, 1: 8804 } };

beforeEach(() => {
  (fetchData as jest.Mock).mockReset();
});

describe("the payload gate", () => {
  test("a non-geo spec over a GeoDataFrame carries no geometry", () => {
    return prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "bar", encoding: { x: { field: "zip" }, y: { field: "pop" } } },
    ).then(({ values }) => {
      expect(values[0].geometry).toBeUndefined();
      expect(values[0]).toEqual({ zip: "60601", pop: 2746, __row_index__: 0 });
    });
  });

  test("a geoshape spec over the same payload does carry it", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "geoshape" },
    );

    expect(values[0].geometry.type).toBe("Feature");
  });
});

describe("input types", () => {
  test("a rejected input type reports a reason rather than throwing", async () => {
    // This used to throw from an unawaited async call, so nothing caught it and
    // the toast it was meant to raise never appeared.
    const result = await prepareVegaInput({ dataType: "raster", data: {} }, { mark: "bar" });

    expect(result.emptyReason).toBe("input-type-rejected");
    expect(result.values).toEqual([]);
  });

  test("an empty input is simply no rows", async () => {
    expect((await prepareVegaInput("", { mark: "bar" })).values).toEqual([]);
    expect((await prepareVegaInput(null, { mark: "bar" })).values).toEqual([]);
  });
});

describe("fetching", () => {
  test("reads by path when the payload is a reference", async () => {
    (fetchData as jest.Mock).mockResolvedValue({ data: framePayload });

    const { values } = await prepareVegaInput(
      { dataType: "dataframe", path: "art-12" },
      { mark: "bar" },
    );

    expect(fetchData).toHaveBeenCalledWith("art-12");
    expect(values).toHaveLength(2);
  });

  test("uses inline data when there is no path", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "dataframe", data: framePayload },
      { mark: "bar" },
    );

    expect(fetchData).not.toHaveBeenCalled();
    expect(values[0].zip).toBe("60601");
  });
});

describe("row index", () => {
  test("__row_index__ is positional and survives the geo passes", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "geoshape" },
    );

    expect(values.map((v: any) => v.__row_index__)).toEqual([0, 1]);
  });
});

describe("a plain DataFrame carrying geometry", () => {
  test("is still coerced when the spec asks for a geojson field", async () => {
    // `pd.DataFrame(gdf)` produces this: no declared geometry_name, geometry
    // values sitting in ordinary columns. Gating on the spec rather than the
    // dataType is what makes it work.
    const { values, emptyReason } = await prepareVegaInput(
      { dataType: "dataframe", data: { where: { 0: polygon } } },
      { mark: "geoshape" },
    );

    expect(emptyReason).toBeUndefined();
    expect(values[0].where.type).toBe("Feature");
  });
});

describe("several inputs (#662)", () => {
  const both = { dataType: "outputs", data: [
    { dataType: "dataframe", data: framePayload },
    { dataType: "geodataframe", data: geoPayload },
  ] };
  // A bar chart of the first input layered over a map of the second.
  const layered = () => ({
    layer: [
      { mark: "bar", encoding: { x: { field: "zip" }, y: { field: "pop" } } },
      { data: { name: "input_1" }, mark: "geoshape" },
    ],
  });

  test("each input is a dataset named by its circle, its rows marked with the input they came from", async () => {
    const { datasets, emptyReason } = await prepareVegaInputs(both, layered());
    expect(emptyReason).toBeUndefined();
    expect(datasets.map((d) => d.name)).toEqual(["input_0", "input_1"]);
    expect(datasets[0].values.map((v: any) => [v.zip, v.__row_index__, v.__input__]))
      .toEqual([["60601", 0, 0], ["60602", 1, 0]]);
    // Row indexes restart for each input.
    expect(datasets[1].values.map((v: any) => [v.__row_index__, v.__input__])).toEqual([[0, 1], [1, 1]]);
  });

  test("geometry is attached to an input only when a view draws it", async () => {
    const spec: any = layered();
    const { datasets } = await prepareVegaInputs(both, spec);
    expect(datasets[1].values[0].geometry.type).toBe("Feature");
    expect(spec.layer[1].encoding.shape).toEqual({ field: "geometry", type: "geojson" });

    // The same map input, read only by a bar chart: no geometry inlined.
    const bars = { layer: [{ mark: "bar" }, { data: { name: "input_1" }, mark: "bar" }] };
    const plain = await prepareVegaInputs(both, bars);
    expect(plain.datasets[1].values[0].geometry).toBeUndefined();
  });

  test("an input a view draws as a map but that has no geometry says so", async () => {
    const spec = { layer: [{ mark: "bar" }, { data: { name: "input_1" }, mark: "geoshape" }] };
    const twoFrames = { dataType: "outputs", data: [both.data[1], both.data[0]] };
    expect((await prepareVegaInputs(twoFrames, spec)).emptyReason).toBe("geometry-unresolved");
  });

  test("one input is input_0, read by every view, with no input mark on its rows", async () => {
    const { datasets } = await prepareVegaInputs({ dataType: "dataframe", data: framePayload }, { mark: "bar" });
    expect(datasets.map((d) => d.name)).toEqual(["input_0"]);
    expect(datasets[0].values[0].__input__).toBeUndefined();
  });

  test("an input it cannot read is refused by its circle, so no name points at another input's rows", async () => {
    const withRaster = { dataType: "outputs", data: [both.data[0], { dataType: "raster", data: {} }, both.data[0]] };
    expect(await prepareVegaInputs(withRaster, layered())).toEqual({
      datasets: [],
      emptyReason: "input-type-rejected",
      detail: "raster at position 1 is not a valid input for the 2D Plot (Vega-Lite).",
    });
  });

  test("prepareVegaInput hands back the first input's rows", async () => {
    const { values } = await prepareVegaInput(both, { mark: "bar" });
    expect(values.map((v: any) => v.zip)).toEqual(["60601", "60602"]);
  });
});

describe("a layer chip in the spec reads the frame its input carries (#662)", () => {
  // The chips resolve against the scope the node builds (hook/useInputScope):
  // each wired circle with the value it holds, before any column is read.
  const resolvedSpec = (text: string, values: unknown[]) => {
    const inputs = inputScopeFor(
      "chart",
      values.map((_, slot) => ({
        source: `up-${slot}`, target: "chart", sourceHandle: "out", targetHandle: slot === 0 ? "in" : `in_${slot}`,
      })),
      [],
      (slot) => values[slot],
      () => null,
      () => undefined,
    );
    const { code, problems } = resolveReferences(text, { widgets: [], inputs, shared: [] }, "json");
    expect(problems).toEqual([]);
    return JSON.parse(code);
  };

  test("a view reads the rows of the one frame the input it names carries, whatever the chip names", async () => {
    const slots = [
      { dataType: "dataframe", data: framePayload },
      { dataType: "geodataframe", data: geoPayload },
    ];
    const spec = resolvedSpec(
      '{"layer": [{"mark": "bar"}, {"data": {"name": [!! input_1:zips !!]}, "mark": "geoshape"}]}',
      slots,
    );
    const { datasets, emptyReason } = await prepareVegaInputs({ dataType: "outputs", data: slots }, spec);
    expect(emptyReason).toBeUndefined();
    injectInputs(spec, datasets);
    const read = spec.layer[1].data.name;
    expect(Object.keys(spec.datasets)).toContain(read);
    expect(spec.datasets[read].map((row: any) => [row.zip, row.__input__])).toEqual([["60601", 1], ["60602", 1]]);
  });

  test("with one input, a view that names it through a layer chip reads its rows", async () => {
    const input = { dataType: "dataframe", data: framePayload };
    const spec = resolvedSpec(
      '{"layer": [{"data": {"name": [!! input_0:zips !!]}, "mark": "bar", "encoding": {"x": {"field": "zip"}}}]}',
      [input],
    );
    const { datasets } = await prepareVegaInputs(input, spec);
    expect(injectInputs(spec, datasets)).toBe(true);
    const read = spec.layer[0].data.name;
    expect(Object.keys(spec.datasets)).toContain(read);
    expect(spec.datasets[read].map((row: any) => row.zip)).toEqual(["60601", "60602"]);
  });
});

describe("injectInputs", () => {
  const rowsOf = (name: string) => ({ name, values: [{ name }] });

  test("one input read by the whole spec is its top-level data, as before", () => {
    const spec: any = { mark: "bar", data: { name: "anything" } };
    expect(injectInputs(spec, [rowsOf("input_0")])).toBe(false);
    expect(spec.data).toEqual({ values: [{ name: "input_0" }], name: "input_0" });
    expect(spec.datasets).toBeUndefined();
  });

  test("several inputs are named datasets, and the top level reads the first unless it names another", () => {
    const spec: any = { mark: "bar", datasets: { mine: [1] } };
    expect(injectInputs(spec, [rowsOf("input_0"), rowsOf("input_1")])).toBe(true);
    expect(spec.datasets).toEqual({ mine: [1], input_0: [{ name: "input_0" }], input_1: [{ name: "input_1" }] });
    expect(spec.data).toEqual({ name: "input_0" });

    const second: any = { data: { name: "input_1" }, mark: "bar" };
    injectInputs(second, [rowsOf("input_0"), rowsOf("input_1")]);
    expect(second.data).toEqual({ name: "input_1" });
  });

  test("one input that a part of the spec names is a named dataset too", () => {
    const spec: any = { layer: [{ mark: "bar" }, { data: { name: "input_0" }, mark: "rule" }] };
    expect(injectInputs(spec, [rowsOf("input_0")])).toBe(true);
    expect(Object.keys(spec.datasets)).toEqual(["input_0"]);
    expect(spec.data).toEqual({ name: "input_0" });
  });
});

describe("usesNamedDatasets", () => {
  test("several inputs always do", () => {
    expect(usesNamedDatasets({ mark: "bar" }, 2)).toBe(true);
  });

  test("one input does when a layer, a concatenated view, a facet's view or a lookup names a dataset", () => {
    expect(usesNamedDatasets({ mark: "bar" }, 1)).toBe(false);
    expect(usesNamedDatasets({ data: { name: "input_0" }, mark: "bar" }, 1)).toBe(false);
    expect(usesNamedDatasets({ layer: [{ data: { name: "input_0" }, mark: "bar" }] }, 1)).toBe(true);
    expect(usesNamedDatasets({ hconcat: [{ mark: "bar" }, { data: { name: "input_0" }, mark: "bar" }] }, 1)).toBe(true);
    expect(usesNamedDatasets({ facet: { row: { field: "a" } }, spec: { data: { name: "input_0" }, mark: "bar" } }, 1)).toBe(true);
    expect(usesNamedDatasets({
      mark: "bar",
      transform: [{ lookup: "zip", from: { data: { name: "input_0" }, key: "zip", fields: ["pop"] } }],
    }, 1)).toBe(true);
  });

  test("a view bringing its own rows names no dataset", () => {
    expect(usesNamedDatasets({ layer: [{ data: { url: "x.json", name: "x" }, mark: "bar" }] }, 1)).toBe(false);
  });

  test("one input does when the spec's own data names inputs, every input stacked", () => {
    expect(usesNamedDatasets({ data: { name: "inputs" }, mark: "bar" }, 1)).toBe(true);
    expect(usesNamedDatasets({ data: { name: "inputs" }, mark: "bar" }, 0)).toBe(true);
  });
});

describe("readsInputs: a spec that names the dataset inputs anywhere", () => {
  test("in its own data, a layer's, a concatenated view's, a facet's view or a lookup", () => {
    expect(readsInputs({ data: { name: "inputs" }, mark: "bar" })).toBe(true);
    expect(readsInputs({ layer: [{ mark: "bar" }, { data: { name: "inputs" }, mark: "rule" }] })).toBe(true);
    expect(readsInputs({ vconcat: [{ mark: "bar" }, { data: { name: "inputs" }, mark: "bar" }] })).toBe(true);
    expect(readsInputs({ facet: { row: { field: "a" } }, spec: { data: { name: "inputs" }, mark: "bar" } })).toBe(true);
    expect(readsInputs({
      mark: "bar",
      transform: [{ lookup: "zip", from: { data: { name: "inputs" }, key: "zip", fields: ["pop"] } }],
    })).toBe(true);
  });

  test("not a spec that names only its inputs one by one, or rows of its own called inputs", () => {
    expect(readsInputs({ mark: "bar" })).toBe(false);
    expect(readsInputs({ data: { name: "input_0" }, layer: [{ data: { name: "input_1" }, mark: "bar" }] })).toBe(false);
    expect(readsInputs({ data: { name: "inputs", values: [{ a: 1 }] }, mark: "bar" })).toBe(false);
  });
});

describe("injectInputs with the stacked dataset", () => {
  const rows = (name: string) => ({ name, values: [{ name }] });

  test("one input: a spec whose own data names inputs keeps naming it, never given input_0's rows", () => {
    const spec: any = { data: { name: "inputs" }, mark: "bar" };
    expect(injectInputs(spec, [rows("input_0")])).toBe(true);
    expect(spec.data).toEqual({ name: "inputs" });
    expect(spec.datasets).toEqual({ input_0: [{ name: "input_0" }] });

    const stacked: any = { data: { name: "inputs" }, mark: "bar" };
    expect(injectInputs(stacked, [rows("input_0"), rows("inputs")])).toBe(true);
    expect(stacked.data).toEqual({ name: "inputs" });
    expect(stacked.datasets).toEqual({ input_0: [{ name: "input_0" }], inputs: [{ name: "inputs" }] });
  });

  test("several inputs: a layer reads inputs, the top level reads the first input", () => {
    const spec: any = { data: { name: "inputs" }, layer: [{ mark: "bar" }, { data: { name: "input_1" }, mark: "rule" }] };
    expect(injectInputs(spec, [rows("input_0"), rows("input_1"), rows("inputs")])).toBe(true);
    expect(Object.keys(spec.datasets)).toEqual(["input_0", "input_1", "inputs"]);
    expect(spec.data).toEqual({ name: "inputs" });

    const layered: any = { layer: [{ mark: "bar" }, { data: { name: "inputs" }, mark: "rule" }] };
    injectInputs(layered, [rows("input_0"), rows("input_1"), rows("inputs")]);
    expect(layered.data).toEqual({ name: "input_0" });
    expect(usesNamedDatasets({ data: { name: "inputs" }, mark: "bar" }, 1)).toBe(true);
  });

  test("nothing arrived: inputs is no rows, and so is the first input the top level reads", () => {
    const spec: any = { layer: [{ data: { name: "inputs" }, mark: "bar" }] };
    expect(injectInputs(spec, [rows("inputs")])).toBe(true);
    expect(spec.datasets).toEqual({ inputs: [{ name: "inputs" }], input_0: [] });
    expect(spec.data).toEqual({ name: "input_0" });
  });
});

describe("prepareVegaInputs stacks every input for a spec that reads inputs", () => {
  const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
  const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };
  const BARS = {
    data: { name: "inputs" },
    mark: "bar",
    encoding: { x: { field: "scenario_name" }, y: { field: "sunlight", aggregate: "mean" } },
  };
  const frame = (sunlight: number[]) => ({
    dataType: "dataframe",
    data: { segment: sunlight.map((_, i) => `r${i + 1}`), sunlight },
  });
  const both = (...inputs: any[]) => ({ dataType: "outputs", data: inputs });
  const named = (prepared: { datasets: { name: string; values: any[] }[] }, name: string) =>
    prepared.datasets.find((d) => d.name === name)?.values;

  test("two inputs: each row under its circle, its box's id and its box's name, in circle order", async () => {
    const prepared = await prepareVegaInputs(both(frame([5, 6]), frame([3])), BARS, [BASE, TALL]);
    expect(prepared.emptyReason).toBeUndefined();
    expect(prepared.datasets.map((d) => d.name)).toEqual(["input_0", "input_1", "inputs"]);
    expect(named(prepared, "inputs")).toEqual([
      { segment: "r1", sunlight: 5, __row_index__: 0, __input__: 0, scenario: "s-base", scenario_name: "Baseline" },
      { segment: "r2", sunlight: 6, __row_index__: 1, __input__: 0, scenario: "s-base", scenario_name: "Baseline" },
      { segment: "r1", sunlight: 3, __row_index__: 0, __input__: 1, scenario: "s-tall", scenario_name: "Twice as tall" },
    ]);
    expect(prepared.stacked).toBe(named(prepared, "inputs"));
    // Each input's own dataset stays its own rows.
    expect(named(prepared, "input_0")).toEqual([
      { segment: "r1", sunlight: 5, __row_index__: 0, __input__: 0 },
      { segment: "r2", sunlight: 6, __row_index__: 1, __input__: 0 },
    ]);

    // A spec that does not read inputs stacks nothing from the same inputs.
    const plain = await prepareVegaInputs(both(frame([5, 6]), frame([3])), { mark: "bar" }, [BASE, TALL]);
    expect(plain.datasets.map((d) => d.name)).toEqual(["input_0", "input_1"]);
    expect(plain.stacked).toBeUndefined();
    expect(named(plain, "input_0")![0]).not.toHaveProperty("scenario_name");
  });

  test("one input: stacked under its box too, and injected as a named dataset", async () => {
    const spec: any = JSON.parse(JSON.stringify(BARS));
    const prepared = await prepareVegaInputs(frame([4]), spec, [TALL]);
    expect(named(prepared, "inputs")).toEqual([
      { segment: "r1", sunlight: 4, __row_index__: 0, __input__: 0, scenario: "s-tall", scenario_name: "Twice as tall" },
    ]);
    expect(injectInputs(spec, prepared.datasets)).toBe(true);
    expect(spec.data).toEqual({ name: "inputs" });
    expect(spec.datasets.inputs).toHaveLength(1);
  });

  test("an input with no label is named by its circle, with no scenario", async () => {
    const prepared = await prepareVegaInputs(both(frame([5]), frame([3])), BARS, [BASE]);
    expect(named(prepared, "inputs")!.map((row: any) => [row.scenario, row.scenario_name])).toEqual([
      ["s-base", "Baseline"],
      [null, "input_1"],
    ]);
  });

  test("a value is a row under value, which only a spec reading inputs takes", async () => {
    const values = both({ dataType: "float", data: 5.5 }, { dataType: "list", data: [{ dataType: "int", data: 3 }] });
    const prepared = await prepareVegaInputs(values, BARS, [BASE, TALL]);
    expect(prepared.emptyReason).toBeUndefined();
    expect(named(prepared, "inputs")).toEqual([
      { value: 5.5, __input__: 0, scenario: "s-base", scenario_name: "Baseline" },
      { value: 3, __input__: 1, scenario: "s-tall", scenario_name: "Twice as tall" },
    ]);
    expect(named(prepared, "input_1")).toEqual([{ value: 3, __row_index__: 0, __input__: 1 }]);

    const refused = await prepareVegaInputs(both(frame([5]), { dataType: "float", data: 5.5 }), { mark: "bar" });
    expect(refused).toEqual({
      datasets: [],
      emptyReason: "input-type-rejected",
      detail: "float at position 1 is not a valid input for the 2D Plot (Vega-Lite).",
    });
  });

  test("one input that is a value: its rows are the value's, under its box", async () => {
    const prepared = await prepareVegaInputs({ dataType: "int", data: 7 }, BARS, [TALL]);
    expect(prepared.datasets).toEqual([
      { name: "input_0", values: [{ value: 7, __row_index__: 0 }] },
      { name: "inputs", values: [{ value: 7, __input__: 0, scenario: "s-tall", scenario_name: "Twice as tall" }] },
    ]);
    expect((await prepareVegaInputs({ dataType: "int", data: 7 }, { mark: "bar" })).emptyReason).toBe("input-type-rejected");
  });

  test("inputs that cannot be stacked: nothing to draw, and the refusal says why", async () => {
    const clash = { dataType: "dataframe", data: { scenario: ["mine"], sunlight: [1] } };
    const prepared = await prepareVegaInputs(both(frame([5]), clash), BARS, [BASE, TALL]);
    expect(prepared.emptyReason).toBe("input-type-rejected");
    expect(prepared.detail).toBe(
      'The dataset "inputs": input_1 (Twice as tall) already has a column named scenario. '
        + "Rename it in the node that feeds it: the stacked table adds its own.",
    );
    expect(prepared.stacked).toEqual([]);
    expect(named(prepared, "inputs")).toEqual([]);
  });
});

describe("unresolvable geometry", () => {
  test("a geoshape over data with no geometry reports it", async () => {
    const { emptyReason } = await prepareVegaInput(
      { dataType: "dataframe", data: framePayload },
      { mark: "geoshape" },
    );

    expect(emptyReason).toBe("geometry-unresolved");
  });
});
