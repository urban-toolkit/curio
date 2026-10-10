/**
 * A Vega-Lite node comparing scenarios: the columns a spec reads, the inputs
 * stacked under their scenarios, the scenarios' colors and order put into the
 * spec, and what each scenario lacks.
 */
import { specFields } from "../../utils/vegaSpecFields";
import {
  applyScenarioDefaults, compareStarterSpec, normalizeVegaCompare, requiredColumns,
  scenarioRequirements, stackScenarios, type ScenarioInput,
} from "../../utils/vegaCompare";

const inputs: ScenarioInput[] = [
  { slot: 0, label: { scenario: "no-nbs", name: "No NbS", color: "#e76f51" } },
  { slot: 1, label: { scenario: "all-nbs", name: "All NbS", color: "#2a9d8f" } },
];

describe("specFields", () => {
  it("reads encodings, facets and sort fields", () => {
    expect(specFields({
      facet: { field: "period" },
      spec: { mark: "bar", encoding: { x: { field: "scenario_name" }, y: { field: "median flood depth", aggregate: "mean" }, color: { field: "scenario_name", sort: { field: "rank" } } } },
    })).toEqual(["period", "scenario_name", "median flood depth", "rank"]);
  });

  it("reads what transforms read and leaves out what they make", () => {
    expect(specFields({
      transform: [
        { fold: ["duration", "distance"], as: ["metric", "amount"] },
        { calculate: "datum.amount * datum['unit scale']", as: "scaled" },
        { filter: "datum.scaled > 0" },
        { aggregate: [{ op: "mean", field: "scaled", as: "avg" }], groupby: ["metric", "scenario_name"] },
      ],
      mark: "bar",
      encoding: { x: { field: "metric" }, y: { field: "avg" } },
    })).toEqual(["duration", "distance", "unit scale", "scenario_name"]);
  });

  it("reads a density's field but not the value it makes", () => {
    expect(specFields({ transform: [{ density: "depth", groupby: ["scenario_name"] }], mark: "line", encoding: { x: { field: "value" }, y: { field: "density" } } }))
      .toEqual(["depth", "scenario_name"]);
  });

  it("reads layers and the column of a nested path", () => {
    expect(specFields({ layer: [{ encoding: { x: { field: "a.b" } } }, { encoding: { text: { field: "c\\.d" } } }] }))
      .toEqual(["a", "c.d"]);
  });
});

describe("requiredColumns", () => {
  it("leaves out the node's own scenario columns", () => {
    expect(requiredColumns({ mark: "bar", encoding: { x: { field: "scenario_name" }, y: { field: "Mean Acc shadow" }, color: { field: "scenario" } } }))
      .toEqual(["Mean Acc shadow"]);
  });
});

describe("stackScenarios", () => {
  it("stacks the inputs in circle order under their scenarios", () => {
    const stacked = stackScenarios(
      [{ name: "input_1", values: [{ depth: 4.9 }] }, { name: "input_0", values: [{ depth: 7.16 }] }],
      inputs,
    );
    expect(stacked.name).toBe("scenarios");
    expect(stacked.values).toEqual([
      { depth: 7.16, scenario: "no-nbs", scenario_name: "No NbS", scenario_color: "#e76f51", scenario_order: 0 },
      { depth: 4.9, scenario: "all-nbs", scenario_name: "All NbS", scenario_color: "#2a9d8f", scenario_order: 1 },
    ]);
  });

  it("names an input with no label by its circle", () => {
    expect(stackScenarios([{ name: "input_2", values: [{ v: 1 }] }], inputs).values[0].scenario_name).toBe("input_2");
  });
});

describe("applyScenarioDefaults", () => {
  it("reads the scenarios, in their colors and circle order", () => {
    const spec = applyScenarioDefaults({ mark: "bar", encoding: { x: { field: "scenario_name" }, color: { field: "scenario_name" } } }, inputs);
    expect(spec.data).toEqual({ name: "scenarios" });
    expect(spec.encoding.color.scale).toEqual({ domain: ["No NbS", "All NbS"], range: ["#e76f51", "#2a9d8f"] });
    expect(spec.encoding.x.sort).toEqual(["No NbS", "All NbS"]);
  });

  it("keeps what the spec sets itself", () => {
    const spec = applyScenarioDefaults({
      data: { name: "input_0" },
      layer: [{ encoding: { color: { field: "scenario", scale: { scheme: "set2" } }, x: { field: "scenario_name", sort: "-y" } } }],
    }, inputs);
    expect(spec.data).toEqual({ name: "input_0" });
    expect(spec.layer[0].encoding.color.scale).toEqual({ scheme: "set2" });
    expect(spec.layer[0].encoding.x.sort).toBe("-y");
  });

  it("colors by scenario id when the spec encodes the id", () => {
    const spec = applyScenarioDefaults({ encoding: { fill: { field: "scenario" } } }, inputs);
    expect(spec.encoding.fill.scale.domain).toEqual(["no-nbs", "all-nbs"]);
  });
});

describe("scenarioRequirements", () => {
  it("says what each scenario lacks, and nothing before its input arrives", () => {
    const rows = scenarioRequirements(
      [...inputs, { slot: 2, label: { name: "Later", color: "#8a8f98" } }],
      ["median flood depth", "mean flood depth"],
      new Map([[0, ["median flood depth", "mean flood depth"]], [1, ["median flood depth"]]]),
    );
    expect(rows.map((row) => row.missing)).toEqual([[], ["mean flood depth"], []]);
    expect(rows[2].columns).toBeNull();
  });
});

describe("normalizeVegaCompare", () => {
  it("keeps only a switch that is on", () => {
    expect(normalizeVegaCompare({ enabled: true, extra: 1 })).toEqual({ enabled: true });
    expect(normalizeVegaCompare({ enabled: false })).toBeUndefined();
    expect(normalizeVegaCompare("yes")).toBeUndefined();
  });
});

describe("compareStarterSpec", () => {
  it("bars a number per scenario, or nothing without one", () => {
    const spec = JSON.parse(compareStarterSpec("duration")!);
    expect(spec.data).toBeUndefined();
    expect(spec.encoding.y.field).toBe("duration");
    expect(compareStarterSpec(null)).toBeNull();
  });
});
